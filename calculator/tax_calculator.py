import os
import time
from collections import deque
from decimal import Decimal
from typing import Set

import pandas as pd
from pandas import DataFrame

from calculator.api.exchange_api import ExchangeApi
from calculator.format import (
  PAIR, TIME, SIDE, VALUE_IN_USD, ADJUSTED_VALUE,
  WASH_P_L_IDS, ADJUSTED_SIZE, SIZE_UNIT, P_F_T_UNIT)
from calculator.csv.read_csv import ReadCsv
from calculator.csv.write_output import WriteOutput
from calculator.trade_types import Asset, Side
from calculator.trade_processor.trade_processor import TradeProcessor

exchange_api = ExchangeApi()


def calculate_all(path, cb_name, trade_name, track_wash):
  cost_basis_df = ReadCsv.read("{}{}".format(path, cb_name))
  trades_df = ReadCsv.read("{}{}".format(path, trade_name))

  if track_wash:
    cost_basis_df[ADJUSTED_VALUE] = cost_basis_df[VALUE_IN_USD]
    cost_basis_df[ADJUSTED_SIZE] = Decimal(0)
    cost_basis_df[WASH_P_L_IDS] = pd.Series([] for _ in range(len(trades_df)))
    trades_df[ADJUSTED_VALUE] = trades_df[VALUE_IN_USD]
    trades_df[ADJUSTED_SIZE] = Decimal(0)
    trades_df[WASH_P_L_IDS] = pd.Series([] for _ in range(len(trades_df)))
  assets = get_assets(cost_basis_df, trades_df)
  print(
    "STEP 2: Analyzing trades for the following products\n{}".format(assets)
  )
  output_path = path + "output/"
  if not os.path.isdir(output_path):
    os.mkdir(output_path)
  write_output = WriteOutput(output_path)
  for asset in assets:
    print("Starting to process {}".format(asset))
    base = lambda a: a.get_base_asset()
    quote = lambda a: a.get_quote_asset()
    basis_df = cost_basis_df.loc[
      (
          (
              (cost_basis_df[PAIR].apply(base) == asset) &
              (cost_basis_df[SIDE] == Side.BUY)
          ) | (
              (cost_basis_df[PAIR].apply(quote) == asset) &
              (cost_basis_df[SIDE] == Side.SELL)
          )
      )
    ].sort_values(TIME)

    trades_for_asset_df = trades_df.loc[
      (trades_df[PAIR].apply(quote) == asset) |
      (trades_df[PAIR].apply(base) == asset)
      ].sort_values(TIME)

    processor = calculate_tax_profit_and_loss(
      asset, basis_df, trades_for_asset_df, track_wash)

    print("Finished processing {}, saving results  csv format".format(asset))
    write_output.write(asset, processor.basis_queue, processor.entries)

  # Write summary
  write_output.write_summary()


def calculate_tax_profit_and_loss(
      asset, basis_df, asset_df: pd.DataFrame, track_wash):
  basis_queue = deque(j for i, j in basis_df.iterrows())
  processor = TradeProcessor(asset, basis_queue, track_wash=track_wash)
  trade_count = len(asset_df)
  progress_len = 50
  count = 0
  print("\nProcessing {} trades\n".format(trade_count))
  start = time.time()
  for j, trade in asset_df.iterrows():
    processor.handle_trade(trade)
    count += 1
    chunk = progress_len * count // trade_count
    print("[{}{}]".format("*" * chunk, " " * (progress_len - chunk)), end="\r")
  end = time.time()
  lapsed = end - start
  if trade_count > 0:
    print("\n\nProcessed trades in {} seconds {} per trade\n".format(
      lapsed, lapsed / trade_count))
  return processor


def get_assets(basis_df: DataFrame, trades_df: DataFrame) -> Set[Asset]:
  assets: Set[Asset] = set(basis_df[SIZE_UNIT].unique())
  assets.update(trades_df[SIZE_UNIT].unique())
  assets.update(trades_df[P_F_T_UNIT])
  if Asset.USD in assets:
    assets.remove(Asset.USD)
  return assets
