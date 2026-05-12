"""Trading orders, matching, and trade-fee calculation.

PRD references:
  - §3.5 Order Placement, Matching, and Trading Channels
  - §2.9 Concurrency: ERR_INSUFFICIENT_BALANCE
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_trading_order,
    create_trading_order_payload,
    make_enterprise_headers,
    place_order,
    setup_for_trade_fee_test,
    setup_two_enterprises_with_quota_balances,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.5 — Order shape validation (ERR_INVALID_ORDER)
# ===========================================================================
class TestOrderShape:
    def test_zero_quantity_rejected(self, api):
        """PRD §3.5: 'Order shape violations — non-positive quantity,
        missing limit_price for a LIMIT order, or a limit_price set for a
        MARKET order — are rejected with ERR_INVALID_ORDER.'

        Claim: quantity=0 -> ERR_INVALID_ORDER.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances()
        payload = create_trading_order_payload(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=0,
            channel="EXCHANGE", limit_price=10.00,
        )
        res = api.create_trading_order(
            payload, make_enterprise_headers(seller["id"])
        )
        validate_error(res, "ERR_INVALID_ORDER")

    def test_negative_quantity_rejected(self, api):
        """PRD §3.5: 'Order shape violations — non-positive quantity, ...
        are rejected with ERR_INVALID_ORDER.'

        Claim: quantity<0 -> ERR_INVALID_ORDER.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances()
        payload = create_trading_order_payload(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=-5,
            channel="EXCHANGE", limit_price=10.00,
        )
        res = api.create_trading_order(
            payload, make_enterprise_headers(seller["id"])
        )
        validate_error(res, "ERR_INVALID_ORDER")

    def test_limit_order_without_limit_price_rejected(self, api):
        """PRD §3.5: 'Order shape violations — non-positive quantity,
        missing limit_price for a LIMIT order, ... are rejected with
        ERR_INVALID_ORDER.'

        Claim: LIMIT order with no limit_price -> ERR_INVALID_ORDER.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances()
        payload = create_trading_order_payload(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=10,
            channel="EXCHANGE",
            # limit_price omitted
        )
        res = api.create_trading_order(
            payload, make_enterprise_headers(seller["id"])
        )
        validate_error(res, "ERR_INVALID_ORDER")

    def test_market_order_with_limit_price_rejected(self, api):
        """PRD §3.5: 'Order shape violations — ... or a limit_price set
        for a MARKET order — are rejected with ERR_INVALID_ORDER.'

        Claim: MARKET order WITH limit_price -> ERR_INVALID_ORDER.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances()
        payload = create_trading_order_payload(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="MARKET", quantity=10,
            channel="EXCHANGE", limit_price=10.00,
        )
        res = api.create_trading_order(
            payload, make_enterprise_headers(seller["id"])
        )
        validate_error(res, "ERR_INVALID_ORDER")


# ===========================================================================
# §3.5 — SELL placement requires sufficient balance
# ===========================================================================
class TestSellPlacementBalance:
    def test_sell_without_balance_rejected_with_insufficient_balance(
        self, api
    ):
        """PRD §3.5: 'A SELL placement whose enterprise lacks sufficient
        instrument balance at placement time is rejected with
        ERR_INSUFFICIENT_BALANCE.'

        Claim: an enterprise with quota_balance=0 attempting to SELL 10
        QUOTA -> ERR_INSUFFICIENT_BALANCE.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00, buyer_quota=0.00,
        )
        # The buyer has zero quota balance.
        payload = create_trading_order_payload(
            enterprise_id=buyer["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=10,
            channel="EXCHANGE", limit_price=50.00,
        )
        res = api.create_trading_order(
            payload, make_enterprise_headers(buyer["id"])
        )
        validate_error(res, "ERR_INSUFFICIENT_BALANCE")


# ===========================================================================
# §3.5 — Order placement success
# ===========================================================================
class TestOrderPlacementSuccess:
    def test_sell_limit_with_balance_creates_open_order(self):
        """PRD §3.5: 'On creation, the server records placed_at, sets
        filled_quantity to zero, and the order begins in status OPEN.'

        Claim: a fundable SELL LIMIT order with no immediate match starts
        in status=OPEN, filled_quantity=0, placed_at non-null.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00,
        )
        order = place_order(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=10,
            channel="EXCHANGE", limit_price=999.00,  # too high to match
        )
        assert_trading_order(order)
        assert order["status"] == "OPEN"
        assert order["filled_quantity"] == 0
        assert order.get("placed_at") is not None


# ===========================================================================
# §3.5 — Cancellation
# ===========================================================================
class TestCancelOrder:
    def test_owner_can_cancel_open_order(self, api):
        """PRD §3.5: 'An enterprise may cancel its own order while it is
        in OPEN or PARTIALLY_FILLED; the order transitions to CANCELLED.'

        Claim: owner's cancel on an OPEN order -> CANCELLED.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00,
        )
        order = place_order(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=10,
            channel="EXCHANGE", limit_price=999.00,
        )
        res = api.cancel_trading_order(
            order["id"], make_enterprise_headers(seller["id"])
        )
        cancelled = validate_success(res, expected_status=200)
        assert cancelled["status"] == "CANCELLED"

    def test_non_owner_cancel_rejected_with_ownership_violation(self, api):
        """PRD §3.5: 'Cancellation by another enterprise is rejected with
        ERR_OWNERSHIP_VIOLATION.'

        Claim: non-owner cancel -> ERR_OWNERSHIP_VIOLATION.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00,
        )
        order = place_order(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=10,
            channel="EXCHANGE", limit_price=999.00,
        )
        res = api.cancel_trading_order(
            order["id"], make_enterprise_headers(buyer["id"])
        )
        validate_error(res, "ERR_OWNERSHIP_VIOLATION")


# ===========================================================================
# §3.5 — Trade fee marginal-tier calculation
# ===========================================================================
class TestTradeFee:
    def test_exchange_match_within_tier1_only(self, api, regulator_headers):
        """PRD §3.5: 'Three tiers are defined by gross-value breakpoints:
        tier 1 covers gross values from zero up to and including 100,000
        (the full base rate applies); tier 2 covers the portion strictly
        above 100,000 up to and including 1,000,000 (80% of the base rate
        applies on this portion only); tier 3 covers the portion strictly
        above 1,000,000 (60% of the base rate applies on this portion only).'

        Claim: an EXCHANGE trade with gross_value=50,000 (entirely in
        tier 1) charges fee = 50000 * 0.0010 = 50.00 per side.
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00,
        )
        # 1000 qty at 50.00 = 50_000 gross.
        place_order(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=1000,
            channel="EXCHANGE", limit_price=50.00,
        )
        place_order(
            enterprise_id=buyer["id"],
            side="BUY", instrument="QUOTA",
            order_type="MARKET", quantity=1000,
            channel="EXCHANGE",
        )
        trades_res = api.list_trades(regulator_headers, params={"limit": 50})
        trades = trades_res.json()["data"]
        assert trades, "Expected at least one Trade after a match"
        t = next((x for x in trades
                  if x.get("buy_order_id") and x.get("sell_order_id")), None)
        assert t is not None
        assert t["gross_value"] == pytest.approx(50_000.00, abs=0.01)
        assert t["buyer_fee"] == pytest.approx(50.00, abs=0.01)
        assert t["seller_fee"] == pytest.approx(50.00, abs=0.01)

    def test_exchange_match_across_tier1_and_tier2(
        self, api, regulator_headers
    ):
        """PRD §3.5: 'tier 1 covers gross values from zero up to and
        including 100,000 (the full base rate applies); tier 2 covers the
        portion strictly above 100,000 up to and including 1,000,000 (80%
        of the base rate applies on this portion only) ... The fee per
        side equals the tier-1 portion times the base rate, plus the
        tier-2 portion times the base rate times 0.80, plus the tier-3
        portion times the base rate times 0.60, with the result rounded
        half-up to two decimal places at the very end.'

        Claim: EXCHANGE trade gross_value=200,000 yields fee per side =
        100000*0.0010 + 100000*0.0010*0.80 = 100.00 + 80.00 = 180.00.
        """
        # quantity * price = 4000 * 50 = 200_000 gross
        cyc, seller, buyer, orders = setup_for_trade_fee_test(
            quantity=4000, price=50.00, channel="EXCHANGE"
        )
        trades_res = api.list_trades(regulator_headers, params={"limit": 50})
        trades = trades_res.json()["data"]
        assert trades, "Expected at least one Trade after a match"
        t = next((x for x in trades
                  if x.get("sell_order_id") == orders["sell"]["id"]
                  and x.get("buy_order_id") == orders["buy"]["id"]), None)
        if t is None:
            t = trades[0]  # fall through to first trade
        assert t["gross_value"] == pytest.approx(200_000.00, abs=0.01)
        assert t["buyer_fee"] == pytest.approx(180.00, abs=0.01)
        assert t["seller_fee"] == pytest.approx(180.00, abs=0.01)
