"""Wash sale basis adjustment and window boundary.

Coverage targets (PRD §3.6, §2.10):
- Wash sale window is symmetric ±30 calendar days, inclusive.
- Settle of a loss-SELL with a prior BUY in window writes
  WashSaleEvent, sets disallowed_loss_cents, boosts replacement
  Lot.adjusted_unit_cost_cents.
- Day +30 inside, day +31 outside.
- Pre-flight ERR_WASH_SALE_VIOLATION on BUY execute when a SELL of the
  same group settled within last 30 days.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    buy_and_settle,
    create_trade,
    create_security,
    execute_and_settle,
    execute_trade,
    iso_instant_utc,
    re_get_trade,
    sell_and_settle,
    set_pricing,
    setup_active_client_with_account,
    setup_wash_sale_scenario,
    validate_error,
)


# ===========================================================================
# Wash sale window — day ±30 inclusive — PRD §2.10 / §3.6
# ===========================================================================
class TestWashSaleWindow:

    def test_buy_day_plus_30_inside_window(self, api):
        """PRD §2.10: "The wash sale window is symmetric and
        inclusive: thirty calendar days before through thirty
        calendar days after the calendar date of the realized loss".

        Claim: with a SELL realizing a loss on day 0 and a BUY of the
        substantially-identical security on day +30 (inclusive),
        settling the SELL produces disallowed_loss_cents > 0 on the
        SELL trade.
        """
        scenario = setup_wash_sale_scenario(
            sell_date_iso=iso_instant_utc(2024, 10, 1),
            buy_offset_days=30,  # day +30 inclusive.
        )
        # Set clock to sell date, drop price on S_a so the SELL
        # realizes a loss, and execute+settle SELL.
        advance_clock_to(iso_instant_utc(2024, 10, 1, 12, 0, 0))
        set_pricing(scenario["security_a"], 9_000)  # loss vs 10000
        sell = sell_and_settle(
            scenario["account"], scenario["security_a"], 10,
            cost_basis_method="FIFO",
        )
        # Loss realized: (10*9000) - (10*10000) = -10000 cents.
        assert sell["realized_gain_loss_cents"] < 0, (
            "SELL must realize a loss for wash sale to apply"
        )
        # With a BUY of substantially-identical security in window:
        assert sell.get("disallowed_loss_cents", 0) > 0, (
            f"day +30 must be inside the inclusive window; "
            f"disallowed_loss_cents={sell.get('disallowed_loss_cents')}"
        )

    def test_buy_day_plus_31_outside_window(self, api):
        """PRD §2.10: "The wash sale window is symmetric and
        inclusive: thirty calendar days before through thirty
        calendar days after the calendar date of the realized loss".

        Claim: a BUY at day +31 is outside the inclusive window;
        settling the SELL produces disallowed_loss_cents == 0 on the
        trade.
        """
        scenario = setup_wash_sale_scenario(
            sell_date_iso=iso_instant_utc(2024, 10, 1),
            buy_offset_days=31,  # day +31 outside.
        )
        advance_clock_to(iso_instant_utc(2024, 10, 1, 12, 0, 0))
        set_pricing(scenario["security_a"], 9_000)
        sell = sell_and_settle(
            scenario["account"], scenario["security_a"], 10,
            cost_basis_method="FIFO",
        )
        assert sell["realized_gain_loss_cents"] < 0
        assert sell.get("disallowed_loss_cents", 0) == 0, (
            f"day +31 must be outside the inclusive window; "
            f"disallowed_loss_cents={sell.get('disallowed_loss_cents')}"
        )


# ===========================================================================
# Pre-flight ERR_WASH_SALE_VIOLATION — PRD §3.6
# ===========================================================================
class TestWashSalePreflight:

    def test_buy_execute_blocked_by_recent_sell(self, api):
        """PRD §3.6: "The same wash-sale logic governs the rebalance
        pre-flight: a rebalance child BUY whose target security would
        match a SELL of the same group settled within the last thirty
        calendar days on the same account is rejected at request time
        with ERR_WASH_SALE_VIOLATION rather than being permitted to
        settle and trigger the adjustment. The pre-flight applies to
        every BUY execute path — client-initiated trades, rebalance
        children, dividend reinvest, and harvest replacement."

        Claim: a client-initiated BUY of a substantially-identical
        security executed within 30 days after a settled SELL at a
        loss is rejected with ERR_WASH_SALE_VIOLATION (422).
        """
        scenario = setup_wash_sale_scenario(
            sell_date_iso=iso_instant_utc(2024, 10, 1),
            buy_offset_days=120,  # well outside any window pre-buy
        )
        # First settle a SELL realizing a loss.
        advance_clock_to(iso_instant_utc(2024, 10, 1, 12, 0, 0))
        set_pricing(scenario["security_a"], 9_000)
        sell = sell_and_settle(
            scenario["account"], scenario["security_a"], 10,
            cost_basis_method="FIFO",
        )
        assert sell["realized_gain_loss_cents"] < 0
        # Now try a client BUY of substantially-identical sec_b
        # within 30 days of the SELL settle date.
        advance_clock_to(iso_instant_utc(2024, 10, 20, 12, 0, 0))
        set_pricing(scenario["security_b"], 9_000)
        trade = create_trade(
            scenario["account"], scenario["security_b"],
            side="BUY", requested_shares=2,
        )
        resp = api.execute_trade(
            scenario["account"]["id"], trade["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_WASH_SALE_VIOLATION.value,
        )
