"""Staff workload (planned vs actual) and the cancellation/release invariants."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    api_client,
    setup_dual_variant_workload,
    setup_billing_register_invariant,
    setup_workload_conservation_invariant,
    setup_scheduled_general_case,
    cancel_case,
    schedule_case,
    make_staff_assignment,
    get_settlement_for_case,
)


SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty Rule 1.2 — planned vs actual workload on a single staff ──

def test_planned_workload_includes_reserved_and_completed(api):
    """# difficulty: dual_variant_calc/staff_workload_planned_vs_actual_on_staff

    PRD §3.6: 'The forward-looking `planned_workload_minutes` sums
    `assigned_end_minute` minus `assigned_start_minute` over every
    `CaseAssignment` for this staff member whose `status` is one of `RESERVED`,
    `CONFIRMED`, or `COMPLETED` — that is, every still-on-the-books assignment,
    including those not yet started.'

    Recipe: C1 COMPLETED with planned interval 0..60 (60 min), C2 RESERVED
    with planned interval 100..200 (100 min) → planned_workload = 160."""
    bundle = setup_dual_variant_workload()
    res = api.get_staff(bundle["anesth"]["id"], SCHED)
    staff = validate_success(res, 200)
    assert staff["planned_workload_minutes"] == 160


def test_actual_workload_only_completed_using_actual_interval(api):
    """# difficulty: dual_variant_calc/staff_workload_planned_vs_actual_on_staff

    PRD §3.6: 'The chronological `actual_workload_minutes` sums the **owning
    case's** `actual_end_minute` minus `actual_start_minute` over only those
    `CaseAssignment` rows whose `status` is `COMPLETED`, joining each assignment
    to its owning `SurgicalCase`.'

    Recipe: only C1 is COMPLETED; its actual interval is 0..90 → actual_workload = 90."""
    bundle = setup_dual_variant_workload()
    res = api.get_staff(bundle["anesth"]["id"], SCHED)
    staff = validate_success(res, 200)
    assert staff["actual_workload_minutes"] == 90


def test_planned_actual_workload_diverge_when_actual_exceeds_planned(api):
    """# difficulty: dual_variant_calc/staff_workload_planned_vs_actual_on_staff

    PRD §3.6: 'Because the same assignment can contribute different durations to
    the two totals when the actual surgery ran longer or shorter than planned,
    a staff member's planned and actual workloads will routinely differ even
    though they are computed from the same ground-truth set of assignments.'"""
    bundle = setup_dual_variant_workload()
    res = api.get_staff(bundle["anesth"]["id"], SCHED)
    staff = validate_success(res, 200)
    assert staff["planned_workload_minutes"] != staff["actual_workload_minutes"]


# ─── Difficulty Rule 9.1 — settlement billing register conserved on cancel ─

def test_settlement_estimate_persists_through_cancel(api):
    """# difficulty: compensating_invariant/settlement_billing_register_conserved_on_cancel

    PRD §3.7: 'The owning `Settlement` cascades from `DRAFT` to `REFUNDED` with
    its `refund_amount` set to the value of `estimated_total_amount` at the
    moment of cancellation.'

    For the recipe (room@500, anesth@200, scrub@80, planned 0..60, no implants):
    estimated = 930.00; after cancel, refund_amount = 930.00."""
    bundle = setup_billing_register_invariant()
    pre_cancel = get_settlement_for_case(bundle["case"]["id"])
    assert pre_cancel["estimated_total_amount"] == 930.00
    assert pre_cancel["refund_amount"] == 0.00

    cancel_case(bundle["case"]["id"])
    post_cancel = get_settlement_for_case(bundle["case"]["id"])
    assert post_cancel["estimated_total_amount"] == 930.00
    assert post_cancel["refund_amount"] == 930.00


def test_settlement_register_balances_after_cancel(api):
    """# difficulty: compensating_invariant/settlement_billing_register_conserved_on_cancel

    PRD §3.7: 'The owning `Settlement` cascades from `DRAFT` to `REFUNDED` with
    its `refund_amount` set to the value of `estimated_total_amount` at the
    moment of cancellation.'

    Conserved register: estimated_total_amount - refund_amount == 0 after
    cancellation, since refund_amount := estimated_total_amount."""
    bundle = setup_billing_register_invariant()
    cancel_case(bundle["case"]["id"])
    post_cancel = get_settlement_for_case(bundle["case"]["id"])
    diff = post_cancel["estimated_total_amount"] - post_cancel["refund_amount"]
    assert diff == 0.00


# ─── Difficulty Rule 9.2 — workload conserved on release ──────────────────

def test_planned_workload_returns_to_zero_after_cancellation(api):
    """# difficulty: compensating_invariant/staff_planned_workload_minutes_conserved_on_release

    PRD §3.6: 'The forward-looking `planned_workload_minutes` sums ... over every
    `CaseAssignment` for this staff member whose `status` is one of `RESERVED`,
    `CONFIRMED`, or `COMPLETED` ... `RELEASED` and `PREEMPTED` assignments are
    excluded because they no longer represent committed time.'

    PRD §3.7: 'Every `CaseAssignment` on the case (in either `RESERVED` or
    `CONFIRMED`) cascades to `RELEASED`.' — so post-cancel, the assignment is
    RELEASED and planned_workload returns to zero."""
    bundle = setup_workload_conservation_invariant()

    pre_schedule = validate_success(api.get_staff(bundle["anesth"]["id"], SCHED), 200)
    assert pre_schedule["planned_workload_minutes"] == 0

    schedule_case(
        bundle["case"]["id"],
        room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(bundle["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=bundle["instrument"]["id"],
    )

    post_schedule = validate_success(api.get_staff(bundle["anesth"]["id"], SCHED), 200)
    assert post_schedule["planned_workload_minutes"] == 60

    cancel_case(bundle["case"]["id"])

    post_cancel = validate_success(api.get_staff(bundle["anesth"]["id"], SCHED), 200)
    assert post_cancel["planned_workload_minutes"] == 0


def test_planned_workload_pre_and_post_cancel_equal(api):
    """# difficulty: compensating_invariant/staff_planned_workload_minutes_conserved_on_release

    PRD §3.6 (same sentence as above): RELEASED assignments are excluded from
    `planned_workload_minutes`. The conserved quantity is the workload-minutes
    register: after a cancel cycle, the staff member's planned workload returns
    to its pre-schedule value."""
    bundle = setup_workload_conservation_invariant()
    pre = validate_success(api.get_staff(bundle["anesth"]["id"], SCHED), 200)["planned_workload_minutes"]
    schedule_case(
        bundle["case"]["id"],
        room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(bundle["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=bundle["instrument"]["id"],
    )
    cancel_case(bundle["case"]["id"])
    post = validate_success(api.get_staff(bundle["anesth"]["id"], SCHED), 200)["planned_workload_minutes"]
    assert pre == post
