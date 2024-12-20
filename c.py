import requests
import os
import time
import traceback
import telebot
from flask import Flask
import threading 
app = Flask('')

@app.route('/')
def home():
    return "I am alive"

def run_flask():
    try:
        app.run(host='0.0.0.0', port=8085)
    except Exception as e:
        logging.error(f"Error in Flask server: {e}")

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()
    
API_KEY = "e5cfb84e-3fd4-4bad-8660-b913323dd2a9"
TELEGRAM_BOT_TOKEN = "7903221567:AAFsEBoO3NH5EaWCmbArMpCTegojvG6wIpM"
SOURCE_GROUP_ID = "-1002415943593"
TARGET_GROUP_ID = "-1002294723694"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

IGNORED_TOKENS = {
    "so11111111111111111111111111111111111111112",  # SOL
    "wsol",  # Wrapped SOL
    "usdt",  # USDT
}

SIGNATURES_DIR = "signatures"
MONITOR_DURATION = 6 * 3600
MAX_TRANSACTIONS_PER_WALLET = 5

os.makedirs(SIGNATURES_DIR, exist_ok=True)


def fetch_transaction_history(wallet_address, limit=MAX_TRANSACTIONS_PER_WALLET):
    api_url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/transactions?api-key={API_KEY}&limit={limit}"
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transaction history for {wallet_address}: {e}")
        return []


def get_latest_signature(wallet_address):
    file_path = os.path.join(SIGNATURES_DIR, f"{wallet_address}_signature.txt")
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            return file.read().strip()
    return None


def save_latest_signature(wallet_address, signature):
    file_path = os.path.join(SIGNATURES_DIR, f"{wallet_address}_signature.txt")
    with open(file_path, "w") as file:
        file.write(signature)


def parse_transactions(transactions, wallet_address, latest_signature):
    transfers = []
    new_latest_signature = None

    for txn in transactions:
        if txn["signature"] == latest_signature:
            break

        if new_latest_signature is None:
            new_latest_signature = txn["signature"]

        if "tokenTransfers" in txn:
            for transfer in txn["tokenTransfers"]:
                if transfer.get("fromUserAccount") == wallet_address:
                    token_address = transfer.get("mint", "Unknown")
                    if token_address.lower() in IGNORED_TOKENS:
                        continue
                    transfers.append({
                        "wallet_address": wallet_address,
                        "token": token_address,
                    })

    return transfers, new_latest_signature

    return transfers, new_latest_signature

def send_to_telegram(group_id, message):
    payload = {
        "chat_id": group_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(f"{TELEGRAM_URL}sendMessage", json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error sending message to Telegram: {e}")


def fetch_wallets_from_group(offset):
    """
    Fetch new messages from the source Telegram group starting from the given offset.
    """
    try:
        response = requests.get(f"{TELEGRAM_URL}getUpdates", params={"offset": offset, "timeout": 30})
        response.raise_for_status()
        updates = response.json().get("result", [])
        wallets = []
        new_offset = offset

        for update in updates:
            if "message" in update:
                message = update["message"]
                chat_id = str(message.get("chat", {}).get("id"))
                if chat_id == SOURCE_GROUP_ID and "text" in message:
                    text = message["text"].strip()
                    if len(text) == 44:
                        wallets.append(text)
                new_offset = max(new_offset, update["update_id"] + 1)

        if not wallets:
            print(f"No valid wallet addresses found in group {SOURCE_GROUP_ID}.")
        
        return list(set(wallets)), new_offset
    except requests.exceptions.RequestException as e:
        print(f"Error fetching wallets from Telegram group: {e}")
        return [], offset

def monitor_wallet(wallet_address):
    print(f"Monitoring wallet: {wallet_address}")
    latest_signature = get_latest_signature(wallet_address)

    transactions = fetch_transaction_history(wallet_address)
    if not transactions:
        print(f"No transactions found for wallet: {wallet_address}.")
        send_to_telegram(
            SOURCE_GROUP_ID, 
            f"No transfers going on for wallet: `{wallet_address}`."
        )
        return False

    transfers, new_latest_signature = parse_transactions(transactions, wallet_address, latest_signature)

    if transfers:
        count = 0
        for transfer in transfers:
            if count >= MAX_TRANSACTIONS_PER_WALLET:
                break
            send_to_telegram(
                TARGET_GROUP_ID,
                f"*New Transfer Detected*\nToken: `{transfer['token']}`\nWallet: `{transfer['wallet_address']}`",
            )
            count += 1
    else:
        send_to_telegram(
            SOURCE_GROUP_ID, 
            f"No transfers going on for wallet: `{wallet_address}`."
        )

    if new_latest_signature:
        save_latest_signature(wallet_address, new_latest_signature)

    return True

def main():
    """
    Main function that polls the Telegram bot and monitors wallets.
    If any error occurs, it waits 5 seconds and restarts.
    """
    wallet_start_times = {}
    offset = 0
    monitored_wallets = []

    print("Starting the bot...")
    while True:
        try:
            wallets, offset = fetch_wallets_from_group(offset)
            if wallets:
                monitored_wallets.extend(wallets)

            monitored_wallets = list(set(monitored_wallets))
            current_time = time.time()

            for wallet in monitored_wallets[:]:
                if wallet not in wallet_start_times:
                    wallet_start_times[wallet] = current_time
                if current_time - wallet_start_times[wallet] > MONITOR_DURATION:
                    print(f"Wallet {wallet} monitoring duration expired.")
                    monitored_wallets.remove(wallet)
                    continue

                if monitor_wallet(wallet):
                    time.sleep(2)
        except Exception as e:
            print("An error occurred:", str(e))
            print(traceback.format_exc())
            print("Restarting after 5 seconds...")
            time.sleep(5)
            
if __name__ == "__main__":
    keep_alive()
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped manually.")
    except Exception as e:
        print("Unexpected error:", str(e))
        print(traceback.format_exc())
