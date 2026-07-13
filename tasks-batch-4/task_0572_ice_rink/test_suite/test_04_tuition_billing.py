"""Recurring tuition: the two divergent proration algorithms on cancellation,
and the ACTIVE<->PAST_DUE billing cycle."""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_diverging_tuition, setup_active_subscription,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/tuition_refund_calendar_vs_sessions_diverge
# ---------------------------------------------------------------------------
def test_calendar_proration_refund_on_cancel(api):
    """PRD §3.4: "Under `CALENDAR` mode, let the total number of days in the cycle
    be the count of days from `billing_cycle_start` up to `billing_cycle_end`, and
    let the days remaining be the count of days from the cancellation date up to
    `billing_cycle_end`, floored at zero so a cancellation on or after the cycle
    end yields no remaining days. The refund is the `monthly_fee_cents` multiplied
    by days remaining, divided by total days, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/tuition_refund_calendar_vs_sessions_diverge
    """
    # fee 12000, cycle 2026-06-01..2026-07-01 (30 days), clock 2026-06-16 (15 left).
    # refund = round_half_up(12000 * 15 / 30) = 6000. Wallet 100000-12000+6000 = 94000.
    setup = setup_diverging_tuition(api)
    sub = validate_success(api.cancel_subscription(setup["sub_a"]["id"], RM))
    assert sub["status"] == "CANCELLED", f"expected CANCELLED, got {sub['status']}"
    sk = validate_success(api.get_skater(setup["skater_a"]["id"], RM))
    assert sk["wallet_credit_cents"] == 94000, (
        f"CALENDAR refund 6000 expected wallet 94000, got {sk['wallet_credit_cents']}")


def test_sessions_proration_refund_on_cancel(api):
    """PRD §3.4: "Under `SESSIONS` mode, let the sessions remaining be
    `total_sessions_in_cycle` minus `sessions_attended`, floored at zero, and the
    refund is the `monthly_fee_cents` multiplied by sessions remaining, divided by
    `total_sessions_in_cycle`, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/tuition_refund_calendar_vs_sessions_diverge
    """
    # fee 12000, 8 sessions total, 5 attended -> 3 remaining.
    # refund = round_half_up(12000 * 3 / 8) = 4500. Wallet 100000-12000+4500 = 92500.
    setup = setup_diverging_tuition(api)
    sub = validate_success(api.cancel_subscription(setup["sub_b"]["id"], RM))
    assert sub["status"] == "CANCELLED", f"expected CANCELLED, got {sub['status']}"
    sk = validate_success(api.get_skater(setup["skater_b"]["id"], RM))
    assert sk["wallet_credit_cents"] == 92500, (
        f"SESSIONS refund 4500 expected wallet 92500, got {sk['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/tuition_active_pastdue_cycle
# ---------------------------------------------------------------------------
def test_advance_then_pay_returns_subscription_to_active(api):
    """PRD §3.4: "Advancing rolls both `billing_cycle_start` and `billing_cycle_end`
    forward by one month, sets `status` to `PAST_DUE`, and increments `version`."
    PRD §3.4: "Paying — a `Skater` or `RinkManager` action — brings a `PAST_DUE`
    subscription back to `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/tuition_active_pastdue_cycle
    """
    # Clock past cycle end so advance-cycle is permitted.
    setup = setup_active_subscription(api, clock="2026-07-02T00:00:00Z",
                                      email="cycle@x.com")
    sub_id = setup["subscription"]["id"]
    past_due = validate_success(api.advance_cycle(sub_id, RM))
    assert past_due["status"] == "PAST_DUE", f"expected PAST_DUE, got {past_due['status']}"
    active = validate_success(api.pay_subscription(sub_id, RM))
    assert active["status"] == "ACTIVE", f"expected ACTIVE after pay, got {active['status']}"


def test_cycle_charges_wallet_twice(api):
    """PRD §3.4: "Paying ... requires that the skater's `wallet_credit_cents` be at
    least the `monthly_fee_cents`, deducts that fee from the wallet, adds it to
    `captured_cents`, sets `status` back to `ACTIVE`, and increments `version`."

    Design: Difficulty/non_linear_state_machine/tuition_active_pastdue_cycle
    """
    # Wallet 100000; create charges 12000 -> 88000; advance charges nothing;
    # pay charges 12000 -> 76000.
    setup = setup_active_subscription(api, clock="2026-07-02T00:00:00Z",
                                      email="cycle2@x.com")
    sub_id = setup["subscription"]["id"]
    validate_success(api.advance_cycle(sub_id, RM))
    validate_success(api.pay_subscription(sub_id, RM))
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 76000, (
        f"two monthly charges of 12000 expected wallet 76000, got {sk['wallet_credit_cents']}")
