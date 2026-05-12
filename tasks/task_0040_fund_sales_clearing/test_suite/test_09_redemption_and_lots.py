"""PRD §3.5 / §3.4: Redemption confirmation cascade and the
conservation invariant on Fund.total_outstanding_shares.

These tests cover the REDEEM confirmation path for orders below the
large-redemption threshold (the deferral path is exercised in
test_10_large_redemption.py). The Rule 9 instance 1 difficulty test
verifies that subscribing 100_000 cents and then redeeming all the
resulting shares brings Fund.total_outstanding_shares back to its
pre-subscribe value.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    ensure_clock_at_least,
    fee_tier,
    get_fund_fresh,
    get_order_fresh,
    holding_period_tier,
    publish_nav_payload,
    setup_basic_investor_and_fund,
    setup_investor_with_confirmed_subscribe,
    submit_redeem_order,
    submit_subscribe_order,
    subscribe_confirm,
    validate_success,
)


class TestRedeemBelowThreshold:
    def test_share_conservation_below_threshold(self, api):
        """PRD §3.4: "For `REDEEM` orders below the threshold and for all
        other order types, confirmation runs from `ACCEPTED → CONFIRMED`
        directly. ... For `REDEEM`, lots are consumed FIFO ... ,
        `Fund.total_outstanding_shares` decreases by the confirmed
        shares."

        Claim: after a SUBSCRIBE that mints 10_000_000 shares and a
        later REDEEM of 100_000 shares (well below the default
        1000 bps threshold), Fund.total_outstanding_shares ==
        9_900_000.

        # difficulty: compensating_invariant/subscribe_then_full_redeem_share_conservation
        """
        investor, fund, order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2026-12-01T10:00:00.000Z",
        )
        assert order["status"] == "CONFIRMED"
        fund_after_sub = get_fund_fresh(fund["id"])
        assert fund_after_sub["total_outstanding_shares"] == 10_000_000

        # Submit REDEEM for 100_000 shares (1 bps of outstanding,
        # well below the default 1000-bps threshold).
        ensure_clock_at_least("2026-12-03T10:00:00.000Z")
        red = submit_redeem_order(
            investor, fund, requested_shares=100_000
        )
        ensure_clock_at_least("2026-12-05T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                # net_assets = 100_000 cents to keep NAV = 1.0 with
                # shares_outstanding = 10_000_000 (1e-4 unit) at
                # trade_date end.
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        assert red_after["status"] == "CONFIRMED", (
            f"Expected CONFIRMED after sub-threshold REDEEM, got "
            f"{red_after['status']!r}"
        )
        fund_after = get_fund_fresh(fund["id"])
        assert fund_after["total_outstanding_shares"] == 9_900_000, (
            f"PRD §3.4 cascade: outstanding -= confirmed_shares; got "
            f"{fund_after['total_outstanding_shares']}"
        )

    def test_full_redeem_via_high_threshold_returns_outstanding_to_zero(self, api):
        """PRD §3.5: "the order's `confirmed_amount_cents` is the gross
        redemption amount minus `redemption_fee_cents` minus
        `back_end_load_fee_cents`, and `confirmed_shares` equals the
        original `requested_shares`." Combined with PRD §3.4 cascade
        ("`Fund.total_outstanding_shares` decreases by the confirmed
        shares").

        Claim: with a fund whose large_redemption_threshold_pct_bps is
        raised above the actual redemption ratio, a full REDEEM of
        every outstanding share brings Fund.total_outstanding_shares
        back to 0 (exact integer equality, no drift).

        # difficulty: compensating_invariant/subscribe_then_full_redeem_share_conservation
        """
        # Threshold raised to a large value so 100% redemption stays
        # below threshold and goes through the direct-CONFIRMED path
        # rather than the deferral path. PRD §3.2: the threshold field
        # is in bps and 10000 bps = 100%.
        investor, fund, order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2027-01-05T10:00:00.000Z",
            fund_overrides={
                "large_redemption_threshold_pct_bps": 100_000,  # 1000% (unreachable)
                "subscription_fee_tiers": [fee_tier(0, None, 0)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        assert order["status"] == "CONFIRMED"
        fund_after_sub = get_fund_fresh(fund["id"])
        assert fund_after_sub["total_outstanding_shares"] == 10_000_000

        # Full REDEEM of all 10_000_000 shares.
        ensure_clock_at_least("2027-01-07T10:00:00.000Z")
        red = submit_redeem_order(
            investor, fund, requested_shares=10_000_000
        )
        ensure_clock_at_least("2027-01-09T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        assert red_after["status"] == "CONFIRMED", (
            f"PRD §3.4: with threshold raised above ratio, full REDEEM "
            f"confirms directly; got {red_after['status']!r}"
        )
        fund_final = get_fund_fresh(fund["id"])
        assert fund_final["total_outstanding_shares"] == 0, (
            f"PRD §3.4: after a SUBSCRIBE-confirm + full REDEEM-confirm "
            f"cycle, Fund.total_outstanding_shares restores exactly to "
            f"its pre-subscribe value (0); got "
            f"{fund_final['total_outstanding_shares']}"
        )
