"""Cost-basis lot selection (FIFO vs HIFO) on disposal, and the depth-4 trade
execution cascade through Trade -> Balance -> CostBasisLot -> taker volume."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, find_balance, find_lot_by_unit_cost,
    assert_cost_basis_lot, ApiErrorId,
    set_clock, create_eth_asset, create_usd_btc_with_fees,
    create_account_at_tier, create_and_credit_deposit, setup_account_with_two_eth_lots,
    withdraw_to_broadcast, setup_trade_match_scenario, place_order,
)

OP = TEST_USERS["operator_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc — FIFO vs HIFO lot depletion on disposal
# ===========================================================================
def test_fifo_account_depletes_oldest_cheapest_lot(api):
    """PRD §3.10: "Under `FIFO` the lots are ordered oldest first — by `acquired_at`
    ascending, then `created_at` ascending."
    PRD §3.10: "decrements the lot's `remaining_quantity`, marks the lot `DEPLETED`
    if it reaches zero"

    Design: Difficulty/dual_variant_calc/cost_basis_fifo_vs_hifo_lot_depletion
    """
    set_clock("2026-01-01T00:00:00Z")
    create_eth_asset(required_confirmations=2)
    acc, addr = setup_account_with_two_eth_lots("FIFO", "fifo@x.com", "FIFO Trader")
    acc_id = acc["id"]
    # dispose 1.0 ETH via withdrawal -> BROADCAST
    withdraw_to_broadcast(acc_id, addr["id"], 1.0, officer_user_id="co-1")
    trader = make_trader_headers(acc_id)
    lots, _ = validate_paginated(api.list_cost_basis_lots(
        trader, params={"account_id": acc_id, "asset": "ETH"}))
    lot_1500 = find_lot_by_unit_cost(lots, 1500)
    lot_2500 = find_lot_by_unit_cost(lots, 2500)
    # FIFO consumes the older 1500 lot first
    assert lot_1500["status"] == "DEPLETED"
    assert lot_1500["remaining_quantity"] == pytest.approx(0.0, abs=1e-9)
    assert lot_2500["status"] == "OPEN"
    assert lot_2500["remaining_quantity"] == pytest.approx(1.0, abs=1e-9)


def test_hifo_account_depletes_most_expensive_lot(api):
    """PRD §3.10: "Under `HIFO` the lots are ordered most-expensive first — by
    `unit_cost_usd` descending, then `acquired_at` ascending."
    PRD §3.10: "marks the lot `DEPLETED` if it reaches zero"

    Design: Difficulty/dual_variant_calc/cost_basis_fifo_vs_hifo_lot_depletion
    """
    set_clock("2026-01-01T00:00:00Z")
    create_eth_asset(required_confirmations=2)
    acc, addr = setup_account_with_two_eth_lots("HIFO", "hifo@x.com", "HIFO Trader")
    acc_id = acc["id"]
    withdraw_to_broadcast(acc_id, addr["id"], 1.0, officer_user_id="co-1")
    trader = make_trader_headers(acc_id)
    lots, _ = validate_paginated(api.list_cost_basis_lots(
        trader, params={"account_id": acc_id, "asset": "ETH"}))
    lot_1500 = find_lot_by_unit_cost(lots, 1500)
    lot_2500 = find_lot_by_unit_cost(lots, 2500)
    # HIFO consumes the most-expensive 2500 lot first
    assert lot_2500["status"] == "DEPLETED"
    assert lot_2500["remaining_quantity"] == pytest.approx(0.0, abs=1e-9)
    assert lot_1500["status"] == "OPEN"
    assert lot_1500["remaining_quantity"] == pytest.approx(1.0, abs=1e-9)


# ===========================================================================
# Difficulty / transitive_cascade — depth-4 trade execution cascade
# ===========================================================================
def test_trade_cascade_settles_balances_and_creates_buy_lot(api):
    """PRD §3.8: "The two accounts' balances are settled: base moves from seller to
    buyer and quote moves from buyer to seller, net of fees."
    PRD §3.8: "A cost-basis lot of `origin_type` `TRADE_BUY` is opened for the
    buyer's acquired base"

    Design: Difficulty/transitive_cascade/trade_execution_depth4_cascade
    """
    seller, maker, buyer = setup_trade_match_scenario(
        clock="2026-07-01T00:00:00Z", sell_price=40000, buyer_usd=50000)
    place_order(buyer["id"], "BTC", "USD", "BUY", "MARKET", 1.0, time_in_force="IOC")
    trader = make_trader_headers(buyer["id"])
    # Link2: buyer BTC available == 1.0
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": buyer["id"], "asset": "BTC"}))
    btc = find_balance(bals, "BTC")
    assert btc["available_amount"] == pytest.approx(1.0, abs=1e-9)
    # Link3: a TRADE_BUY lot of 1.0 BTC at unit_cost 40000
    lots, _ = validate_paginated(api.list_cost_basis_lots(
        trader, params={"account_id": buyer["id"], "asset": "BTC"}))
    buy_lots = [l for l in lots if l["origin_type"] == "TRADE_BUY"]
    assert len(buy_lots) == 1
    lot = buy_lots[0]
    assert lot["remaining_quantity"] == pytest.approx(1.0, abs=1e-9)
    assert lot["unit_cost_usd"] == pytest.approx(40000, abs=0.01)
    assert_cost_basis_lot(lot)


def test_trade_cascade_recomputes_taker_volume(api):
    """PRD §3.8: "Finally, both accounts' `taker_volume_30d_usd` and `fee_tier` are
    recomputed."
    PRD §3.9: "the `taker_volume_30d_usd` field is the analogous sum where the
    account was the aggressing taker side"

    Design: Difficulty/transitive_cascade/trade_execution_depth4_cascade
    """
    seller, maker, buyer = setup_trade_match_scenario(
        clock="2026-07-01T00:00:00Z", sell_price=40000, buyer_usd=50000)
    place_order(buyer["id"], "BTC", "USD", "BUY", "MARKET", 1.0, time_in_force="IOC")
    trader = make_trader_headers(buyer["id"])
    acc = validate_success(api.get_account(buyer["id"], trader))
    # Link4: buyer was the taker; notional 40000 rolls into taker_volume_30d_usd
    assert acc["taker_volume_30d_usd"] == pytest.approx(40000, abs=0.01)
