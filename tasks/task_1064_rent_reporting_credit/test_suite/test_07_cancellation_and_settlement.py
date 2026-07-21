"""Cancellation: prorated settlement (rounding order + conserved money) and the
depth-4 terminate/retract/recompute cascade.

Covers prorated settlement (rounding order and conserved money) and the
terminate/retract/recompute cancellation cascade.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers,
    assert_money_conserved,
    reset_clock_default, create_tenant, create_plan, create_enrollment,
    setup_active_enrollment_for_cancel, setup_reported_item,
)


# --------------------------------------------------------------------------
# Difficulty: dual_variant_calc / prorated refund (pinned variant)
# --------------------------------------------------------------------------
def test_cancel_active_sets_cancelled_and_prorated_refund(api):
    """PRD §3.8: "The `refund_cents` is the paid-this-period amount minus the
    earned amount, floored at zero so it is never negative."

    Design: Difficulty/dual_variant_calc/cancellation_settlement_prorated_vs_accrual_diverge
    """
    ctx = setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z", monthly_fee_cents=1499)
    th = make_tenant_headers(ctx["tenant"]["id"])
    data = validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    assert data["status"] == "CANCELLED"
    assert data["refund_cents"] == 1015


def test_cancel_active_earned_is_prorated_rounded(api):
    """PRD §3.8: "The `earned_cents` is the `monthly_fee_cents` multiplied by days
    used divided by period length, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/cancellation_settlement_prorated_vs_accrual_diverge
    """
    ctx = setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z", monthly_fee_cents=1499)
    th = make_tenant_headers(ctx["tenant"]["id"])
    data = validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    assert data["earned_cents"] == 484


# --------------------------------------------------------------------------
# Difficulty: combinatorial_formula / settlement evaluation order (mode c)
# --------------------------------------------------------------------------
def test_cancel_settlement_split_values(api):
    """PRD §3.8: "The `earned_cents` is the `monthly_fee_cents` multiplied by days
    used divided by period length, rounded half up to whole cents. The
    `refund_cents` is the paid-this-period amount minus the earned amount, floored
    at zero".

    Design: Difficulty/combinatorial_formula/cancellation_settlement_eval_order_mode_c
    """
    ctx = setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z", monthly_fee_cents=1499)
    th = make_tenant_headers(ctx["tenant"]["id"])
    data = validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    assert data["earned_cents"] == 484
    assert data["refund_cents"] == 1015


def test_cancel_settlement_conserves_paid_amount(api):
    """PRD §3.8: "When the period was paid, earned plus refund exactly equals the
    paid amount, conserving the money."

    Design: Difficulty/combinatorial_formula/cancellation_settlement_eval_order_mode_c
    """
    ctx = setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z", monthly_fee_cents=1499)
    th = make_tenant_headers(ctx["tenant"]["id"])
    data = validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    assert_money_conserved(data["earned_cents"], data["refund_cents"], 1499)


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / cancellation conserves period money
# --------------------------------------------------------------------------
def test_cancellation_conserves_period_cash(api):
    """PRD §3.8: "When the period was paid, earned plus refund exactly equals the
    paid amount, conserving the money."

    Design: Difficulty/compensating_invariant/cancellation_conserves_period_money
    """
    ctx = setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z", monthly_fee_cents=1499)
    th = make_tenant_headers(ctx["tenant"]["id"])
    data = validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    assert data["earned_cents"] + data["refund_cents"] == 1499


def test_cancellation_period_money_split_matches(api):
    """PRD §3.8: "The `earned_cents` is the `monthly_fee_cents` multiplied by days
    used divided by period length, rounded half up to whole cents."

    Design: Difficulty/compensating_invariant/cancellation_conserves_period_money
    """
    ctx = setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z", monthly_fee_cents=1499)
    th = make_tenant_headers(ctx["tenant"]["id"])
    data = validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    assert data["earned_cents"] == 484
    assert data["refund_cents"] == 1015


# --------------------------------------------------------------------------
# Difficulty: transitive_cascade / cancel -> terminate -> retract -> recompute
# --------------------------------------------------------------------------
def test_cancel_cascade_terminates_lease_and_retracts_item(api):
    """PRD §3.8: "Every lease of this tenant currently in `VERIFIED` transitions to
    the terminal `TERMINATED`. Each such termination in turn retracts that lease's
    still-effective tradelines: every reported item on the lease whose `status` is
    `REPORTED` or `DISPUTED` moves to `RETRACTED` with its `bureau_statuses` all
    set to `DELETED`."

    Design: Difficulty/transitive_cascade/cancel_terminates_lease_retracts_item_recomputes_rate
    """
    ctx = setup_reported_item(api, property_address="7 Birch Ln")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    lease = validate_success(api.get_lease(th, ctx["lease"]["id"]), 200)
    assert lease["verification_status"] == "TERMINATED"
    item = validate_success(api.get_reported_item(th, ctx["item"]["id"]), 200)
    assert item["status"] == "RETRACTED"


def test_cancel_cascade_recomputes_tenant_statistics(api):
    """PRD §3.8: "because those retractions change the effective set, the tenant's
    `reported_on_time_rate_pct` and `effective_reported_items` are recomputed once
    the cascade settles."
    PRD §2.7: "`reported_on_time_rate_pct` is null when the tenant has no effective
    reported items, and `effective_reported_items` is zero in that case."

    Design: Difficulty/transitive_cascade/cancel_terminates_lease_retracts_item_recomputes_rate
    """
    ctx = setup_reported_item(api, property_address="7b Birch Ln")
    th = make_tenant_headers(ctx["tenant"]["id"])
    validate_success(api.cancel_enrollment(th, ctx["enrollment"]["id"]), 200)
    summary = validate_success(api.get_credit_summary(th, ctx["tenant"]["id"]), 200)
    assert summary["effective_reported_items"] == 0
    assert summary["on_time_rate_as_reported_pct"] is None


# --------------------------------------------------------------------------
# Corner: cancelling a CANCELLED enrollment is invalid
# --------------------------------------------------------------------------
def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.8: "A tenant cancels their enrolment, which is always allowed from
    either `PENDING_PAYMENT` or `ACTIVE` and drives the enrolment to the terminal
    `CANCELLED`".

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Dan Double", email="dan@x.com")
    enrollment = create_enrollment(api, tenant["id"], plan["id"])
    th = make_tenant_headers(tenant["id"])
    validate_success(api.cancel_enrollment(th, enrollment["id"]), 200)
    resp = api.cancel_enrollment(th, enrollment["id"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
