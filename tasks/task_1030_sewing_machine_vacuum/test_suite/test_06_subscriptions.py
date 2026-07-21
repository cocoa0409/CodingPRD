"""Tune-up subscriptions: prorated cancellation refunds and tune-up exhaustion."""
from test_helpers import (
    TEST_USERS,
    set_clock,
    setup_active_subscription_with_period,
    validate_error,
    validate_success,
)

SA = TEST_USERS["sales_associate_headers"]
ST = TEST_USERS["service_tech_headers"]


# ───────────────── proration rounding order (multiply-first) ───────────────
def test_proration_refund_multiplies_before_dividing(api):
    """PRD §3.7: "the refund is `monthly_fee_cents` multiplied by the unused days,
    divided by the period length in days, rounded half up to whole cents — the
    integer fee is multiplied by the integer unused-day count first, then divided by
    the period days, and rounded exactly once at the end (the per-day rate is never
    rounded on its own)."

    Design: Difficulty/combinatorial_formula/subscription_proration_rounding_order
    """
    cust, sub = setup_active_subscription_with_period(
        period_start="2026-07-01T00:00:00Z", monthly_fee_cents=3100, plan_tier="BASIC",
    )
    set_clock("2026-07-11T00:00:00Z")  # 20 unused days of 30
    cancelled = validate_success(api.cancel_subscription(sub["id"], SA), 200)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_customer(cust["id"], SA), 200)["store_credit_cents"] == 2067


def test_proration_refund_rounds_half_up_once(api):
    """PRD §3.7: "the refund is `monthly_fee_cents` multiplied by the unused days,
    divided by the period length in days, rounded half up to whole cents — the
    integer fee is multiplied by the integer unused-day count first, then divided by
    the period days, and rounded exactly once at the end (the per-day rate is never
    rounded on its own)."

    Design: Difficulty/combinatorial_formula/subscription_proration_rounding_order
    """
    cust, sub = setup_active_subscription_with_period(
        period_start="2026-07-01T00:00:00Z", monthly_fee_cents=5000, plan_tier="PRO",
    )
    set_clock("2026-07-21T00:00:00Z")  # 10 unused days of 30 -> 5000*10/30 = 1666.67 -> 1667
    validate_success(api.cancel_subscription(sub["id"], SA), 200)
    assert validate_success(api.get_customer(cust["id"], SA), 200)["store_credit_cents"] == 1667


# ───────────────── tune-up exhaustion at used == included ──────────────────
def test_redeem_rejected_when_used_equals_included(api):
    """PRD §3.7: "redemption once `tune_ups_used` has reached `tune_ups_included`
    (they are equal) is rejected with `ERR_TUNE_UPS_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/tuneup_used_ge_included_exhausted
    """
    cust, sub = setup_active_subscription_with_period(
        period_start="2026-07-01T00:00:00Z", monthly_fee_cents=5000, plan_tier="PRO",
        tune_ups_included=2,
    )
    validate_success(api.redeem_subscription(sub["id"], ST), 200)
    validate_success(api.redeem_subscription(sub["id"], ST), 200)  # used == included == 2
    res = api.redeem_subscription(sub["id"], ST)
    validate_error(res, "ERR_TUNE_UPS_EXHAUSTED", expected_status=409)


def test_redeem_succeeds_while_used_below_included(api):
    """PRD §3.7: "A redemption succeeds only while the subscription is `ACTIVE`, the
    logical clock is before `current_period_end`, and `tune_ups_used` is strictly
    less than `tune_ups_included`; a successful redemption increases `tune_ups_used`
    by one."

    Design: Difficulty/boundary_precision_check/tuneup_used_ge_included_exhausted
    """
    _cust, sub = setup_active_subscription_with_period(
        period_start="2026-07-01T00:00:00Z", monthly_fee_cents=5000, plan_tier="PRO",
        tune_ups_included=2,
    )
    validate_success(api.redeem_subscription(sub["id"], ST), 200)  # used 0 -> 1
    second = validate_success(api.redeem_subscription(sub["id"], ST), 200)  # used 1 -> 2
    assert second["tune_ups_used"] == 2
