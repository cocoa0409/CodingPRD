"""Delinquency sweeps, hold raising/clearing, and the late-fee compensating
invariant — the ledger-reconciliation side of the plan.

Difficulty queue: dual_variant_calc (hold reason), boundary_precision_check,
transitive_cascade, compensating_invariant (late-fee half).
Corner: state_machine hold-release precondition.
"""
from test_helpers import (
    fixtures,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc (hold reason: count vs amount)
# ===========================================================================
def test_hold_reason_delinquency_count_three_small_installments(api):
    """PRD 3.8: "Delinquency is considered tripped when the overdue count is at
    least 3, or the total overdue amount is at least 150,000 cents — either
    threshold suffices." ... "The hold's `reason` is `DELINQUENCY_COUNT` when
    the count threshold is met and `DELINQUENCY_AMOUNT` otherwise."

    5PAY [40000 x5]: 3 overdue (total 120000 < 150000) trips only the count
    threshold -> reason DELINQUENCY_COUNT.

    Design: Difficulty/dual_variant_calc/hold_reason_count_vs_amount_distinct_thresholds
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=200000, aid_cents=0, installment_count=5, down_payment_pct=0,
        plan_fee_cents=0,
    )
    enr_id = base["enrollment"]["id"]
    student_id = base["student"]["id"]
    # 2026-11-05 puts installments 1,2,3 (dues 09-21/10-11/10-31) past grace.
    fixtures.set_clock(base["institution"]["id"], "2026-11-05T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    enr = fixtures.get_enrollment(enr_id)
    assert enr["delinquent_installment_count"] == 3, enr
    holds = [h for h in fixtures.list_holds(enr_id) if h["status"] == "ACTIVE"]
    assert len(holds) == 1, holds
    assert holds[0]["reason"] == "DELINQUENCY_COUNT", holds[0]
    student = fixtures.get_student(student_id)
    assert student["has_active_hold"] is True, student


def test_hold_reason_delinquency_amount_two_large_installments(api):
    """PRD 3.8: "Delinquency is considered tripped when the overdue count is at
    least 3, or the total overdue amount is at least 150,000 cents — either
    threshold suffices." ... "The hold's `reason` is `DELINQUENCY_COUNT` when
    the count threshold is met and `DELINQUENCY_AMOUNT` otherwise."

    4PAY [80000 x4]: 2 overdue (total 160000 >= 150000, count 2 < 3) trips only
    the amount threshold -> reason DELINQUENCY_AMOUNT.

    Design: Difficulty/dual_variant_calc/hold_reason_count_vs_amount_distinct_thresholds
    """
    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    enr_id = base["enrollment"]["id"]
    assert base["enrollment"]["delinquent_installment_count"] == 2, base["enrollment"]
    holds = [h for h in base["holds"] if h["status"] == "ACTIVE"]
    assert len(holds) == 1, holds
    assert holds[0]["reason"] == "DELINQUENCY_AMOUNT", holds[0]


# ===========================================================================
# Difficulty: boundary_precision_check (count 2 vs 3)
# ===========================================================================
def test_delinquency_count_below_limit_raises_no_hold(api):
    """PRD 3.8: "Delinquency is considered tripped when the overdue count is at
    least 3, or the total overdue amount is at least 150,000 cents" ... "If
    delinquency is tripped and the enrollment has no `ACTIVE` hold, the system
    creates a `Hold`"

    5PAY [40000 x5]: exactly 2 overdue (total 80000) — count 2 < 3 and total
    80000 < 150000 — so NO hold and has_active_hold stays false.

    Design: Difficulty/boundary_precision_check/delinquency_count_boundary_three_vs_two
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=200000, aid_cents=0, installment_count=5, down_payment_pct=0,
        plan_fee_cents=0,
    )
    enr_id = base["enrollment"]["id"]
    student_id = base["student"]["id"]
    # 2026-10-15: only installments 1,2 (dues 09-21/10-11) past grace.
    fixtures.set_clock(base["institution"]["id"], "2026-10-15T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    enr = fixtures.get_enrollment(enr_id)
    assert enr["delinquent_installment_count"] == 2, enr
    active_holds = [h for h in fixtures.list_holds(enr_id) if h["status"] == "ACTIVE"]
    assert active_holds == [], active_holds
    student = fixtures.get_student(student_id)
    assert student["has_active_hold"] is False, student


def test_delinquency_count_at_limit_raises_count_hold(api):
    """PRD 3.8: "Delinquency is considered tripped when the overdue count is at
    least 3" ... "The hold's `reason` is `DELINQUENCY_COUNT` when the count
    threshold is met and `DELINQUENCY_AMOUNT` otherwise."

    Boundary the other side: 5PAY [40000 x5] with exactly 3 overdue (total
    120000 < 150000) raises a DELINQUENCY_COUNT hold.

    Design: Difficulty/boundary_precision_check/delinquency_count_boundary_three_vs_two
    """
    base = fixtures.setup_active_enrollment(
        charges_cents=200000, aid_cents=0, installment_count=5, down_payment_pct=0,
        plan_fee_cents=0,
    )
    enr_id = base["enrollment"]["id"]
    fixtures.set_clock(base["institution"]["id"], "2026-11-05T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    enr = fixtures.get_enrollment(enr_id)
    assert enr["delinquent_installment_count"] == 3, enr
    active_holds = [h for h in fixtures.list_holds(enr_id) if h["status"] == "ACTIVE"]
    assert len(active_holds) == 1, active_holds
    assert active_holds[0]["reason"] == "DELINQUENCY_COUNT", active_holds[0]


# ===========================================================================
# Difficulty: transitive_cascade (run-delinquency -> late fee -> hold -> flag)
# ===========================================================================
def test_run_delinquency_cascades_late_fee_hold_and_student_flag(api):
    """PRD 3.7: "Each installment swept `SCHEDULED -> OVERDUE` runs the
    late-fee assessment, increments the enrollment's `delinquent_installment_count`,
    and runs the delinquency evaluation that may raise a hold."
    PRD 3.8: "If delinquency is tripped and the enrollment has no `ACTIVE` hold,
    the system creates a `Hold` in `ACTIVE` status and sets the student's
    `has_active_hold` to true. The hold's `reason` is `DELINQUENCY_COUNT` when
    the count threshold is met and `DELINQUENCY_AMOUNT` otherwise."

    A single run-delinquency on a 4PAY plan with 2 overdue (total 160000) drives
    SCHEDULED->OVERDUE (hop 1: late fee assessed), creates a DELINQUENCY_AMOUNT
    hold (hop 2), and flips has_active_hold true (hop 3).

    Design: Difficulty/transitive_cascade/overdue_triggers_late_fee_then_hold_then_student_flag
    """
    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    enr_id = base["enrollment"]["id"]
    student_id = base["student"]["id"]

    assert base["enrollment"]["delinquent_installment_count"] == 2, base["enrollment"]
    assessed = [f for f in base["late_fees"] if f["status"] == "ASSESSED"]
    assert len(assessed) >= 1, base["late_fees"]
    active_holds = [h for h in base["holds"] if h["status"] == "ACTIVE"]
    assert len(active_holds) == 1, active_holds
    assert active_holds[0]["reason"] == "DELINQUENCY_AMOUNT", active_holds[0]
    student = fixtures.get_student(student_id)
    assert student["has_active_hold"] is True, student


def test_run_delinquency_cascade_links_late_fee_and_hold_to_enrollment(api):
    """PRD 3.7: "A created `LateFee` belongs to the enrollment, carries its
    `enrollment_id`, the `installment_id` of the overdue installment that
    triggered it"
    PRD 3.8: "A `Hold` belongs to a `Student`, carries its `student_id`, the
    `enrollment_id` of the delinquent enrollment that raised it"

    The cascade's intermediate artifacts are wired through the entity chain: the
    assessed LateFee references an OVERDUE installment, and the ACTIVE Hold
    references the same enrollment whose flip caused has_active_hold to be set.

    Design: Difficulty/transitive_cascade/overdue_triggers_late_fee_then_hold_then_student_flag
    """
    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    enr_id = base["enrollment"]["id"]
    overdue_ids = {i["id"] for i in base["installments"] if i["status"] == "OVERDUE"}
    assert overdue_ids, base["installments"]

    assessed = [f for f in base["late_fees"] if f["status"] == "ASSESSED"]
    assert assessed, base["late_fees"]
    for fee in assessed:
        assert fee["enrollment_id"] == enr_id, fee
        assert fee["installment_id"] in overdue_ids, fee
    active_holds = [h for h in base["holds"] if h["status"] == "ACTIVE"]
    assert active_holds, base["holds"]
    assert active_holds[0]["enrollment_id"] == enr_id, active_holds[0]


# ===========================================================================
# Difficulty: transitive_cascade (withdraw -> cancel installments -> release hold -> flag)
# ===========================================================================
def test_withdraw_cancels_installments_releases_hold_and_clears_flag(api):
    """PRD 3.9: "the enrollment's `delinquent_installment_count` is recomputed
    to zero, and because that falls below the delinquency thresholds, any
    `ACTIVE` hold for this enrollment is released (`ACTIVE -> RELEASED`) and the
    student's `has_active_hold` is recomputed."

    Starting from a delinquent 4PAY plan with an ACTIVE hold, withdrawing drops
    delinquent_installment_count to 0 (hop 1), releases the hold (hop 2), and
    recomputes has_active_hold to false (hop 3).

    Design: Difficulty/transitive_cascade/withdraw_cancels_installments_then_releases_hold_then_flag
    """
    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    enr_id = base["enrollment"]["id"]
    student_id = base["student"]["id"]
    assert any(h["status"] == "ACTIVE" for h in base["holds"]), base["holds"]

    enr = fixtures.withdraw(enr_id, "2026-10-28T00:00:00.000Z")
    assert enr["status"] == "WITHDRAWN", enr
    assert enr["delinquent_installment_count"] == 0, enr
    holds = fixtures.list_holds(enr_id)
    assert holds and all(h["status"] == "RELEASED" for h in holds), holds
    student = fixtures.get_student(student_id)
    assert student["has_active_hold"] is False, student


def test_withdraw_leaves_assessed_late_fees_owed(api):
    """PRD 3.9: "any cancelled installment that was `OVERDUE` and still carried
    an `ASSESSED` late fee leaves that late fee `ASSESSED`: late fees survive
    withdrawal and remain owed."

    The withdrawal cascade cancels installments and releases the hold, but the
    late fee assessed during delinquency survives as ASSESSED and continues to
    count in late_fee_balance_cents — a distinct hop of the same cascade.

    Design: Difficulty/transitive_cascade/withdraw_cancels_installments_then_releases_hold_then_flag
    """
    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    enr_id = base["enrollment"]["id"]
    assessed_before = [f for f in base["late_fees"] if f["status"] == "ASSESSED"]
    assert assessed_before, base["late_fees"]
    balance_before = base["enrollment"]["late_fee_balance_cents"]
    assert balance_before > 0, base["enrollment"]

    fixtures.withdraw(enr_id, "2026-10-28T00:00:00.000Z")

    fees_after = fixtures.list_late_fees(enr_id)
    still_assessed = [f for f in fees_after if f["status"] == "ASSESSED"]
    assert len(still_assessed) == len(assessed_before), fees_after
    enr = fixtures.get_enrollment(enr_id)
    assert enr["late_fee_balance_cents"] == balance_before, enr


# ===========================================================================
# Difficulty: compensating_invariant (late-fee waive conserves balance)
# ===========================================================================
def test_late_fee_waive_restores_late_fee_balance(api):
    """PRD 3.7: "Waiving recomputes `late_fee_balance_cents` as the sum of
    `amount_cents` over the enrollment's fees still in `ASSESSED` status, so the
    waived fee is removed from the balance exactly as a compensating reversal."

    Assessing a 3200 late fee then waiving it returns late_fee_balance_cents to
    its pre-assessment value of 0.

    Design: Difficulty/compensating_invariant/late_fee_waive_conserves_late_fee_balance
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    fixtures.set_clock(base["institution"]["id"], "2026-10-07T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    fees = fixtures.list_late_fees(enr_id)
    assert len(fees) == 1, fees
    fee_id = fees[0]["id"]
    fixtures.get_success_data(api.waive_late_fee(fee_id, REGISTRAR))

    refetched = fixtures.list_late_fees(enr_id)
    waived = [f for f in refetched if f["id"] == fee_id][0]
    assert waived["status"] == "WAIVED", waived
    enr = fixtures.get_enrollment(enr_id)
    assert enr["late_fee_balance_cents"] == 0, enr


def test_late_fee_assessment_adds_to_balance_before_waive(api):
    """PRD 3.7: "An `ASSESSED` fee adds to `late_fee_balance_cents`."
    PRD 3.7: "Waiving recomputes `late_fee_balance_cents` as the sum of
    `amount_cents` over the enrollment's fees still in `ASSESSED` status"

    The forward leg of the conserved-quantity pair: once a 3200 fee is ASSESSED
    the enrollment's late_fee_balance_cents is 3200 (matching the sum of ASSESSED
    fees), establishing the value the compensating waive must restore from.

    Design: Difficulty/compensating_invariant/late_fee_waive_conserves_late_fee_balance
    """
    base = fixtures.setup_active_enrollment(charges_cents=500000, aid_cents=100000)
    enr_id = base["enrollment"]["id"]
    fixtures.settle_down_payment(enr_id, 80000)
    fixtures.set_clock(base["institution"]["id"], "2026-10-07T00:00:00.000Z")
    fixtures.run_delinquency(enr_id)

    fees = [f for f in fixtures.list_late_fees(enr_id) if f["status"] == "ASSESSED"]
    assert len(fees) == 1, fees
    assert fees[0]["amount_cents"] == 3200, fees[0]
    enr = fixtures.get_enrollment(enr_id)
    assert enr["late_fee_balance_cents"] == 3200, enr


# ===========================================================================
# Corner: state_machines / manual hold release while delinquent rejected
# ===========================================================================
def test_manual_hold_release_while_delinquent_rejected(api):
    """PRD 3.8: "A manual release attempted while either threshold is still met
    is rejected with `ERR_DELINQUENCY_UNRESOLVED`."

    Design: Corner/state_machines/hold_release_while_delinquent_returns_unresolved
    """
    from test_helpers import validate_error, ApiErrorId

    base = fixtures.setup_delinquent_enrollment(
        charges_cents=500000, aid_cents=100000, delinquency_clock="2026-10-28T00:00:00.000Z"
    )
    enr_id = base["enrollment"]["id"]
    active_holds = [h for h in base["holds"] if h["status"] == "ACTIVE"]
    assert active_holds, base["holds"]
    hold_id = active_holds[0]["id"]

    resp = api.release_hold(hold_id, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DELINQUENCY_UNRESOLVED.value)
