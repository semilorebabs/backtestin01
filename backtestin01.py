import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import requests

# Initialize MT5 for live trading
if not mt5.initialize():
    print("Failed to initialize MT5")
    quit()

# Bot settings
ACCOUNT_RISK = 0.04  # Max risk per trade (4%)
LOT_SIZE = 0.02  # Fixed lot size
TIMEFRAME = mt5.TIMEFRAME_M5  # 5-minute chart
SYMBOLS = ["EURUSDm", "USDJPYm", "USOILm"]  # List of trading symbols
BACKTEST_BARS = 500  # Number of candles to analyze
FINNHUB_API_KEY = "cv13tq1r01qhkk80jepgcv13tq1r01qhkk80jeq0"
NEWS_API_URL = f"https://finnhub.io/api/v1/calendar/economic?token={FINNHUB_API_KEY}"
MAX_TRADES_PER_PAIR = 4  # Maximum trades per currency pair
BREAK_EVEN_RR = 1.0  # Risk-reward ratio to move SL to break-even

# Fetch historical data
def get_historical_data(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        print(f"Failed to retrieve historical data for {symbol}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# Inside Bar detection
def detect_inside_bar(df):
    df['inside_bar'] = (df['high'].shift(1) > df['high']) & (df['low'].shift(1) < df['low'])
    return df

# Opening Range Breakout (ORB) detection
def detect_orb(df, range_minutes=5):
    opening_range = df.iloc[:range_minutes]
    high, low = opening_range['high'].max(), opening_range['low'].min()
    df['orb_long'] = df['high'] > high
    df['orb_short'] = df['low'] < low
    return df

# RSI Calculation
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period, min_periods=1).mean()
    avg_loss = pd.Series(loss).rolling(window=period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-6)  # Avoid division by zero
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

# MACD Calculation
def calculate_macd(df, short_window=12, long_window=26, signal_window=9):
    df['macd_line'] = df['close'].ewm(span=short_window, adjust=False).mean() - df['close'].ewm(span=long_window, adjust=False).mean()
    df['macd_signal'] = df['macd_line'].ewm(span=signal_window, adjust=False).mean()
    return df

# ATR Calculation
def calculate_atr(df, period=14):
    df['tr'] = np.maximum(df['high'] - df['low'], 
                          np.maximum(abs(df['high'] - df['close'].shift()), 
                                     abs(df['low'] - df['close'].shift())))
    df['atr'] = df['tr'].rolling(window=period, min_periods=1).mean()
    return df

# Check if market is open
def is_market_open(symbol):
    market_info = mt5.symbol_info(symbol)
    if market_info is None or not market_info.visible:
        print(f"Market closed or symbol not available for {symbol}")
        return False
    return True

# Adjust SL and TP
def adjust_sl_tp(symbol, price, sl, tp):
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"Error retrieving info for {symbol}")
        return None, None
    min_distance = symbol_info.trade_stops_level * symbol_info.point
    
    if abs(price - sl) < min_distance:
        sl = price - min_distance if sl < price else price + min_distance
    if abs(price - tp) < min_distance:
        tp = price + min_distance if tp > price else price - min_distance
        
    return sl, tp

# Trade execution
def place_trade(order_type, symbol, price, sl, tp, lot_size, reason):
    if not is_market_open(symbol):
        print(f"Market closed for {symbol}, skipping trade")
        return
    
    sl, tp = adjust_sl_tp(symbol, price, sl, tp)
    if sl is None or tp is None:
        print(f"Invalid SL/TP for {symbol}, skipping trade")
        return
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl,
        "tp": tp,
        "magic": 123456,
        "comment": reason,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    order_result = mt5.order_send(request)
    if order_result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order failed for {symbol}: {order_result.comment}")
    else:
        print(f"Trade placed: {order_type} {symbol} at {price}, SL: {sl}, TP: {tp}")

# Trading loop for live trading
def live_trading():
    while True:
        for symbol in SYMBOLS:
            if not is_market_open(symbol):
                continue
            
            df = get_historical_data(symbol, TIMEFRAME, BACKTEST_BARS)
            if df is None:
                continue
            df = detect_inside_bar(df)
            df = detect_orb(df)
            df = calculate_rsi(df)
            df = calculate_macd(df)
            df = calculate_atr(df)

            for i in range(1, len(df)):
                row = df.iloc[i]
                price = row['close']
                if row['inside_bar'] and price > df.iloc[i-1]['high']:
                    place_trade("BUY", symbol, price, df.iloc[i-1]['low'], price + (price - df.iloc[i-1]['low']) * 2, LOT_SIZE, "Inside Bar Breakout")
                if row['orb_long']:
                    place_trade("BUY", symbol, price, df.iloc[i-1]['low'], price + (price - df.iloc[i-1]['low']) * 2, LOT_SIZE, "Opening Range Breakout")
                if row['orb_short']:
                    place_trade("SELL", symbol, price, df.iloc[i-1]['high'], price - (df.iloc[i-1]['high'] - price) * 2, LOT_SIZE, "Opening Range Breakout")
        time.sleep(60)  # Check every 60 seconds

# Run live trading
if __name__ == "__main__":
    live_trading()
    mt5.shutdown()
