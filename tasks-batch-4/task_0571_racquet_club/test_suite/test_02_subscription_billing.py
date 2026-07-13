"""Subscription lifecycle and recurring billing.

Covers the forward-looking vs chronological period cost, per-active-day proration
rounding, the ACTIVE<->FROZEN cycle, and the freeze / renew / duplicate guards.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_member_with_subscription, make_basic_plan, make_member,
    make_subscription, set_clock, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── dual_variant_calc / dv_subscription_forward_vs_chronological ─────
def test_estimated_period_fee_is_forward_looking_and_ignores_freeze():
    """PRD §3.2: "The forward-looking figure surfaced in estimated_period_fee_cents
    simply equals the plan's monthly_fee_cents and ignores in-period freezes; the
    chronological actual charged at renewal is always less than or equal to that
    forward figure, and the two diverge exactly when a freeze occurred mid-period."

    Design: Difficulty/dual_variant_calc/dv_subscription_forward_vs_chronological_period_cost
    """
    _, _, sub = setup_member_with_subscription()
    set_clock("2026-05-21T00:00:00Z")
    frozen = get_success_data(api_client.freeze_subscription(sub["id"], FD))
    assert frozen["estimated_period_fee_cents"] == 5000


def test_renewal_charges_chronological_prorated_actual():
    """PRD §3.2: "On renewal the subscription is charged the chronological actual
    period fee (defined below), which is posted to the member's account_balance_cents"
    PRD §3.2: "The prorated charge is obtained by rounding the daily rate to the
    nearest cent, half-up, once for each active day, and then summing those per-day
    rounded amounts."

    Design: Difficulty/dual_variant_calc/dv_subscription_forward_vs_chronological_period_cost
    """
    _, member, sub = setup_member_with_subscription()
    set_clock("2026-05-21T00:00:00Z")
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    set_clock("2026-05-31T00:00:00Z")
    get_success_data(api_client.renew_subscription(sub["id"], FD))
    # 20 active days (05-01..05-20) * round_half_up(5000/30=166.6667)=167 -> 3340
    m = validate_success(api_client.get_member(member["id"], FD), 200)
    assert m["account_balance_cents"] == 3340


# ─── combinatorial_formula / combo_subscription_proration_perday_rounding
def test_proration_rounds_per_active_day_then_sums():
    """PRD §3.2: "The prorated charge is obtained by rounding the daily rate to the
    nearest cent, half-up, once for each active day, and then summing those per-day
    rounded amounts."

    Design: Difficulty/combinatorial_formula/combo_subscription_proration_perday_rounding
    """
    _, member, sub = setup_member_with_subscription()
    set_clock("2026-05-16T00:00:00Z")
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    set_clock("2026-05-31T00:00:00Z")
    get_success_data(api_client.renew_subscription(sub["id"], FD))
    # 15 active days * 167 = 2505
    m = validate_success(api_client.get_member(member["id"], FD), 200)
    assert m["account_balance_cents"] == 2505


def test_proration_order_differs_from_sum_then_round():
    """PRD §3.2: "This per-day-rounded-then-summed order is required and is not the
    same as multiplying the daily rate by the active-day count and rounding a single
    time."

    Design: Difficulty/combinatorial_formula/combo_subscription_proration_perday_rounding
    """
    _, member, sub = setup_member_with_subscription()
    set_clock("2026-05-16T00:00:00Z")
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    set_clock("2026-05-31T00:00:00Z")
    get_success_data(api_client.renew_subscription(sub["id"], FD))
    m = validate_success(api_client.get_member(member["id"], FD), 200)
    # per-day round-then-sum = 2505; sum-then-round would be round(166.6667*15)=2500
    assert m["account_balance_cents"] == 2505
    assert m["account_balance_cents"] != 2500


# ─── non_linear_state_machine / freeze-unfreeze cycle ─────────────────
def test_freeze_then_unfreeze_returns_to_active_and_clears_frozen_at():
    """PRD §3.2: "moves a `FROZEN` subscription back to `ACTIVE` and clears `frozen_at`
    to null."

    Design: Difficulty/non_linear_state_machine/nlsm_subscription_freeze_unfreeze_cycle
    """
    _, _, sub = setup_member_with_subscription()
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    unfrozen = get_success_data(api_client.unfreeze_subscription(sub["id"], FD))
    assert unfrozen["status"] == "ACTIVE"
    assert unfrozen["frozen_at"] is None


def test_freeze_count_is_retained_after_unfreeze():
    """PRD §3.2: "A successful manual freeze increments freeze_count by one, stamps
    frozen_at to the current clock instant, and pauses credit accrual so that days
    spent frozen do not count as active days for billing."

    Design: Difficulty/non_linear_state_machine/nlsm_subscription_freeze_unfreeze_cycle
    """
    _, _, sub = setup_member_with_subscription()
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    unfrozen = get_success_data(api_client.unfreeze_subscription(sub["id"], FD))
    assert unfrozen["freeze_count"] == 1


# ─── Corner: freeze_limit_reached_rejected ────────────────────────────
def test_second_freeze_over_limit_rejected():
    """PRD §3.2: "a manual freeze is permitted only while the subscription is ACTIVE
    and its freeze_count is strictly less than the plan's freeze_limit, and a manual
    freeze that would reach or exceed the limit is rejected with
    ERR_FREEZE_LIMIT_REACHED."

    Design: Corner/validations/freeze_limit_reached_rejected
    """
    plan = make_basic_plan()  # freeze_limit 1
    _, _, sub = setup_member_with_subscription(plan=plan)
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    get_success_data(api_client.unfreeze_subscription(sub["id"], FD))
    res = api_client.freeze_subscription(sub["id"], FD)
    validate_error(res, "ERR_FREEZE_LIMIT_REACHED")
    after = validate_success(api_client.get_subscription(sub["id"], FD), 200)
    assert after["freeze_count"] == 1


# ─── Corner: renew_before_period_end_rejected ─────────────────────────
def test_renew_before_period_end_rejected():
    """PRD §3.2: "Renewal closes and reopens the billing period and may run from
    either ACTIVE or FROZEN; it is refused with ERR_RENEW_NOT_DUE unless the current
    clock time has reached current_period_end."

    Design: Corner/validations/renew_before_period_end_rejected
    """
    _, _, sub = setup_member_with_subscription()
    res = api_client.renew_subscription(sub["id"], FD)
    validate_error(res, "ERR_RENEW_NOT_DUE")


# ─── Corner: second_subscription_for_member_rejected ──────────────────
def test_second_subscription_for_member_rejected():
    """PRD §3.2: "A member may hold only one non-CANCELLED subscription at a time;
    attempting to create a second is rejected with ERR_SUBSCRIPTION_EXISTS."

    Design: Corner/validations/second_subscription_for_member_rejected
    """
    plan, member, _ = setup_member_with_subscription()
    from test_helpers import create_subscription_payload
    res = api_client.create_subscription(
        create_subscription_payload(member["id"], plan["id"]), FD)
    validate_error(res, "ERR_SUBSCRIPTION_EXISTS")


# ─── Corner: freeze_already_frozen_subscription_invalid_state ─────────
def test_freeze_already_frozen_subscription_rejected():
    """PRD §3.2: "Freezing moves an ACTIVE subscription to FROZEN"
    PRD §2.8: "State precondition — the target resource is in a state that admits the
    requested transition; otherwise ERR_INVALID_STATE (409). Applies to all
    state-transition operations."

    Design: Corner/state_machines/freeze_already_frozen_subscription_invalid_state
    """
    _, _, sub = setup_member_with_subscription()
    get_success_data(api_client.freeze_subscription(sub["id"], FD))
    res = api_client.freeze_subscription(sub["id"], FD)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api_client.get_subscription(sub["id"], FD), 200)
    assert after["freeze_count"] == 1
