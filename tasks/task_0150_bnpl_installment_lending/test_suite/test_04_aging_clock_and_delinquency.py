"""Clock-driven aging: the grace-window late-fee boundary, the half-open grace
interval, delinquency posture (CURRENT/LATE/DELINQUENT), and the loan's parallel
status x delinquency_status dimensions.

Covers queue A boundary_precision_check (grace boundary), resource_temporal_overlap
(half-open grace window), non_linear_state_machine (parallel loan dimensions), plus
queue B corner instances on the late-fee floor and the LATE->DELINQUENT transition.
"""
from test_helpers import (
    validate_success,
    setup_activated_loan,
    get_loan,
    list_installments,
    installments_by_sequence,
    find_installment,
    make_servicer_headers,
)

SERVICER = make_servicer_headers()


def _advance(api, iso):
    return validate_success(api.set_clock({"to_iso8601": iso}, SERVICER), 200)


def test_late_fee_grace_boundary_strict_greater(api):
    """PRD §3.6: "An installment becomes LATE only when the current instant is strictly
    after its due_date plus the grace period of 10 days; an instant exactly equal to the
    due date plus 10 days is still on time."
    PRD §3.6: "its late_fee_cents is set to that outstanding multiplied by the late-fee
    rate of five percent, rounded half up, then clamped to be at least the floor of 700
    cents and at most the cap of 1500 cents."

    Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_strict_greater
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]

    # At exactly due_date + GRACE_DAYS (2026-01-11) -> still SCHEDULED, no fee.
    _advance(api, "2026-01-11T00:00:00Z")
    inst1 = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1["status"] == "SCHEDULED", "on-time at exactly due+grace boundary"
    assert inst1["late_fee_cents"] == 0

    # One day later (2026-01-12) -> LATE; fee = clamp(round(25000*0.05=1250)) = 1250.
    _advance(api, "2026-01-12T00:00:00Z")
    inst1 = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1["status"] == "LATE"
    assert inst1["late_fee_cents"] == 1250


def test_late_fee_assessed_at_most_once_per_installment(api):
    """PRD §3.6: "A late fee is assessed at most once per installment, so repeated clock
    advances do not re-charge an installment already assessed."

    Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_strict_greater
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]
    _advance(api, "2026-01-12T00:00:00Z")  # inst#1 LATE, fee 1250
    inst1_first = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1_first["late_fee_cents"] == 1250

    _advance(api, "2026-01-15T00:00:00Z")  # advance again; fee must NOT re-charge
    inst1_again = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1_again["late_fee_cents"] == 1250, "fee assessed at most once"


def test_grace_window_half_open_keeps_loan_current_at_boundary(api):
    """PRD §3.6: "If the days-past-due is negative, or the oldest installment is not yet
    past its due date plus the grace period of 10 days, the posture is CURRENT."
    PRD §3.6: "an instant exactly equal to the due date plus 10 days is still on time."

    Design: Difficulty/resource_temporal_overlap/grace_window_half_open_late_determination
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]

    _advance(api, "2026-01-11T00:00:00Z")  # now == due + grace
    loan = get_loan(loan_id)
    assert loan["delinquency_status"] == "CURRENT"
    inst1 = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1["status"] == "SCHEDULED"


def test_grace_window_exit_admits_late_one_day_after_boundary(api):
    """PRD §3.6: "An installment becomes LATE only when the current instant is strictly
    after its due_date plus the grace period of 10 days". PRD §3.6: "If the days-past-due
    is at least the delinquency threshold of 30 days, the posture is DELINQUENT.
    Otherwise — the oldest installment is LATE but its days-past-due is below 30 — the
    posture is LATE."

    Design: Difficulty/resource_temporal_overlap/grace_window_half_open_late_determination
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]
    _advance(api, "2026-01-12T00:00:00Z")  # one day past due+grace -> LATE
    loan = get_loan(loan_id)
    assert loan["delinquency_status"] == "LATE"
    inst1 = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1["status"] == "LATE"


def test_late_fee_floor_clamp_applied_to_small_installment(api):
    """PRD §3.6: "its late_fee_cents is set to that outstanding multiplied by the
    late-fee rate of five percent, rounded half up, then clamped to be at least the
    floor of 700 cents".

    Design: Corner/calculations/late_fee_floor_applied_small_installment
    """
    # financed 12000 PAY_IN_4 -> installments 3000; 5% of 3000 = 150 < floor 700.
    ctx = setup_activated_loan(cart_amount_cents=12_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]

    _advance(api, "2026-01-12T00:00:00Z")
    inst1 = find_installment(installments_by_sequence(list_installments(loan_id)), 1)
    assert inst1["amount_due_cents"] == 3000
    assert inst1["status"] == "LATE"
    assert inst1["late_fee_cents"] == 700, "floor clamp: max(700, round(150)) = 700"


def test_delinquency_posture_late_then_delinquent_across_clock(api):
    """PRD §3.6: "If the days-past-due is at least the delinquency threshold of 30 days,
    the posture is DELINQUENT. Otherwise — the oldest installment is LATE but its
    days-past-due is below 30 — the posture is LATE."

    Design: Corner/cross_cutting_complexity_layers/clock_advance_recomputes_delinquency_to_late_then_delinquent
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]

    # dpd 11 (2026-01-12) -> LATE (past grace, below 30).
    _advance(api, "2026-01-12T00:00:00Z")
    assert get_loan(loan_id)["delinquency_status"] == "LATE"

    # dpd 31 (2026-02-01) -> DELINQUENT (>= 30).
    _advance(api, "2026-02-01T00:00:00Z")
    assert get_loan(loan_id)["delinquency_status"] == "DELINQUENT"


def test_loan_parallel_status_and_delinquency_dimensions(api):
    """PRD §3.5: "in parallel, its delinquency_status is one of CURRENT, LATE, or
    DELINQUENT and evolves independently of the lifecycle, so a loan can be ACTIVE and
    CURRENT or ACTIVE and DELINQUENT at the same time."

    Design: Difficulty/non_linear_state_machine/loan_parallel_status_and_delinquency_dimensions
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]

    _advance(api, "2026-02-01T00:00:00Z")  # dpd 31 -> DELINQUENT
    loan = get_loan(loan_id)
    assert loan["status"] == "ACTIVE", "lifecycle status stays ACTIVE"
    assert loan["delinquency_status"] == "DELINQUENT", "parallel posture is DELINQUENT"


def test_loan_active_and_current_when_not_yet_late(api):
    """PRD §3.5: "so a loan can be ACTIVE and CURRENT or ACTIVE and DELINQUENT at the
    same time." PRD §3.4: "a Loan is created in lifecycle status ACTIVE with
    delinquency_status CURRENT."

    Design: Difficulty/non_linear_state_machine/loan_parallel_status_and_delinquency_dimensions
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan = get_loan(ctx["loan"]["id"])
    # Freshly activated, before any due date passes: ACTIVE + CURRENT (two axes coexist).
    assert loan["status"] == "ACTIVE"
    assert loan["delinquency_status"] == "CURRENT"
