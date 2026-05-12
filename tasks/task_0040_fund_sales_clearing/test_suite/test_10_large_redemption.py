"""PRD §3.4: Large-redemption threshold and deferral.

The threshold comparison is INCLUSIVE -- pct_bps == threshold triggers
deferral. The deferred order has its confirm_date pushed forward by
exactly one calendar day; on the next NAV publication once the new
confirm_date has been reached, the order advances
LARGE_REDEMPTION_DEFERRED -> CONFIRMED.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    add_days,
    advance_clock_to,
    create_kyc_approved_investor,
    ensure_clock_at_least,
    fee_tier,
    get_fund_fresh,
    get_order_fresh,
    holding_period_tier,
    make_investor_headers,
    publish_nav_payload,
    setup_basic_investor_and_fund,
    setup_fund_with_outstanding_shares,
    submit_redeem_order,
    submit_subscribe_order,
    subscribe_confirm,
    validate_success,
)


# Helper that gets two investors holding fixed share counts on the same
# fund, with a known total_outstanding_shares.
def _two_investors_with_shares(
    api,
    *,
    target_outstanding_shares: int,
    investor_a_shares: int,
    investor_b_shares: int,
    threshold_bps: int = 1_000,
):
    """Set up Investor A holding A shares and Investor B holding B shares
    on the same fund, with total_outstanding_shares matching their sum.

    Implementation: create the fund, KYC-approve two investors, fund
    cash, submit two SUBSCRIBE orders sized so each confirms to the
    desired share count at NAV=1.0 (front-end model, 0-bps fees, so
    confirmed_shares = gross_amount_cents * 100).
    """
    assert investor_a_shares % 100 == 0
    assert investor_b_shares % 100 == 0
    assert investor_a_shares + investor_b_shares == target_outstanding_shares

    inv_a = create_kyc_approved_investor(cash_cents=10_000_000_000)
    inv_b = create_kyc_approved_investor(cash_cents=10_000_000_000)

    from test_helpers import create_on_shelf_fund
    fund = create_on_shelf_fund(
        large_redemption_threshold_pct_bps=threshold_bps,
        subscription_fee_tiers=[fee_tier(0, None, 0)],
        redemption_fee_tiers=[holding_period_tier(0, None, 0)],
        management_fee_bps_annual=0,
        custodian_fee_bps_annual=0,
        sales_service_fee_bps_annual=0,
    )
    # Submit at the current clock; trade_date is then determined by the
    # acceptance-window rule against whatever the clock actually is. This
    # keeps the helper monotonicity-safe across a session that may have
    # advanced the clock far ahead of any literal date.
    sub_a = submit_subscribe_order(
        inv_a, fund, gross_amount_cents=investor_a_shares // 100
    )
    sub_b = submit_subscribe_order(
        inv_b, fund, gross_amount_cents=investor_b_shares // 100
    )
    # Advance the clock to strictly after sub_a.trade_date + 1 day so the
    # T+1 NAV publish boundary holds for whatever trade_date the server
    # assigned.
    nav_threshold = add_days(sub_a["trade_date"], 1)
    ensure_clock_at_least(nav_threshold[:10] + "T00:00:01.000Z")
    validate_success(api.publish_nav(
        fund["id"],
        publish_nav_payload(
            nav_date=sub_a["trade_date"].split("T")[0],
            portfolio_market_value_cents=0,
            portfolio_accrued_income_cents=0,
        ),
        TEST_USERS["nav_operator_headers"],
    ), expected_status=201)
    fund_after = get_fund_fresh(fund["id"])
    assert fund_after["total_outstanding_shares"] == target_outstanding_shares, (
        f"Setup failed: expected {target_outstanding_shares}, got "
        f"{fund_after['total_outstanding_shares']}"
    )
    return inv_a, inv_b, fund_after


class TestLargeRedemptionThresholdInclusive:
    def test_at_threshold_deferred(self, api):
        """PRD §3.4: "When that ratio is at or above the fund's
        `large_redemption_threshold_pct_bps` (the boundary is inclusive:
        equality triggers deferral), the order moves `ACCEPTED →
        LARGE_REDEMPTION_DEFERRED` instead of confirming."

        Claim: a REDEEM whose pct_bps == threshold (1000) is deferred,
        not confirmed.

        # difficulty: boundary_precision_check/large_redemption_threshold_inclusive
        """
        inv_a, inv_b, fund = _two_investors_with_shares(
            api,
            target_outstanding_shares=100_000_000,
            investor_a_shares=10_000_000,   # exactly 10% (1000 bps)
            investor_b_shares=90_000_000,
            threshold_bps=1_000,
        )
        # Submit REDEEM at the current clock; the server assigns trade_date.
        red = submit_redeem_order(
            inv_a, fund, requested_shares=10_000_000
        )
        # Advance past red.trade_date + 1 day for the T+1 NAV boundary.
        nav_threshold = add_days(red["trade_date"], 1)
        ensure_clock_at_least(nav_threshold[:10] + "T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                portfolio_market_value_cents=1_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        assert red_after["status"] == "LARGE_REDEMPTION_DEFERRED", (
            f"PRD §3.4: pct_bps=1000 == threshold should defer; got "
            f"status={red_after['status']!r}"
        )
        assert red_after["large_redemption_pct_bps"] == 1000

    def test_below_threshold_confirms(self, api):
        """PRD §3.4: "the boundary is inclusive: equality triggers
        deferral" -- which means pct_bps strictly below the threshold
        does NOT defer.

        Claim: a REDEEM whose pct_bps == 999 is confirmed (not
        deferred).

        # difficulty: boundary_precision_check/large_redemption_threshold_inclusive
        """
        # 9_990_000 / 100_000_000 = 999 bps (rounded half-up).
        inv_a, inv_b, fund = _two_investors_with_shares(
            api,
            target_outstanding_shares=100_000_000,
            investor_a_shares=9_990_000,    # 999 bps
            investor_b_shares=90_010_000,
            threshold_bps=1_000,
        )
        red = submit_redeem_order(
            inv_a, fund, requested_shares=9_990_000
        )
        nav_threshold = add_days(red["trade_date"], 1)
        ensure_clock_at_least(nav_threshold[:10] + "T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                portfolio_market_value_cents=1_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        assert red_after["status"] == "CONFIRMED", (
            f"PRD §3.4: pct_bps=999 < threshold=1000 should NOT defer; "
            f"got status={red_after['status']!r}"
        )
        # NOTE: PRD §3.4 only commits to "captured on the order" along the
        # deferred branch ("the computed `large_redemption_pct_bps` is
        # captured on the order, and `Order.confirm_date` is pushed
        # forward..." — both clauses describe the deferred path). PRD is
        # silent on whether implementations must persist pct_bps on
        # below-threshold orders, so we do not assert that here.


class TestDeferredConfirmationOnNextNav:
    def test_deferred_order_confirms_after_next_nav_publish(self, api):
        """PRD §3.4: "`Order.confirm_date` is pushed forward by exactly
        one calendar day so that the deferred order will be re-evaluated
        against the next NAV publication. ... When the next NAV
        publication arrives and the new `confirm_date` has been reached
        on the server clock, the deferred order advances
        `LARGE_REDEMPTION_DEFERRED → CONFIRMED` using the deferred trade
        date's NAV."

        Claim: after the first NAV publish defers a large REDEEM, a
        SECOND NAV publish (next day) advances the order to CONFIRMED.

        # difficulty: non_linear_state_machine/order_redemption_branching_with_deferral_loop
        """
        inv_a, inv_b, fund = _two_investors_with_shares(
            api,
            target_outstanding_shares=100_000_000,
            investor_a_shares=10_000_000,   # 1000 bps -> deferred
            investor_b_shares=90_000_000,
            threshold_bps=1_000,
        )
        red = submit_redeem_order(
            inv_a, fund, requested_shares=10_000_000
        )
        # Advance past red.trade_date + 1 to satisfy T+1.
        first_nav_threshold = add_days(red["trade_date"], 1)
        ensure_clock_at_least(first_nav_threshold[:10] + "T00:00:01.000Z")
        # First NAV publish -> defers.
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                portfolio_market_value_cents=1_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after_first = get_order_fresh(red["id"])
        assert red_after_first["status"] == "LARGE_REDEMPTION_DEFERRED"
        # Second NAV publish for the next nav_date.
        first_date = red["trade_date"].split("T")[0]
        next_nav_date_iso = add_days(first_date + "T00:00:00.000Z", 1)
        next_nav_date = next_nav_date_iso.split("T")[0]
        # Advance past next_nav_date + 1 day for T+1.
        second_nav_threshold = add_days(next_nav_date + "T00:00:00.000Z", 1)
        ensure_clock_at_least(second_nav_threshold[:10] + "T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=next_nav_date,
                portfolio_market_value_cents=1_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after_second = get_order_fresh(red["id"])
        assert red_after_second["status"] == "CONFIRMED", (
            f"PRD §3.4: deferred order confirms on next NAV publish; "
            f"got status={red_after_second['status']!r}"
        )
