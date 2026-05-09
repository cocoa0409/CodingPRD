"""Case lifecycle: confirm → start → complete; assignment / booking cascades."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_surgical_case,
    approve_case,
    schedule_case,
    confirm_all_assignments,
    list_assignments_for_case,
    start_case,
    complete_case,
    advance_clock,
    setup_scheduled_general_case,
    setup_in_progress_general_case,
    setup_completed_general_case,
    setup_scheduled_case_unconfirmed_for_start,
    setup_cyclic_instrument_state_machine,
    api_client,
)


SCHED = TEST_USERS["scheduler_headers"]


# ─── Confirm assignment ───────────────────────────────────────────────────

def test_confirm_assignment_advances_to_confirmed(api):
    """PRD §3.6: 'Once a case is `SCHEDULED`, each `CaseAssignment` must be
    individually confirmed by a `Scheduler`, advancing the assignment from
    `RESERVED` to `CONFIRMED`'."""
    bundle = setup_scheduled_general_case()
    asgs = list_assignments_for_case(bundle["case"]["id"])
    assert all(a["status"] == "RESERVED" for a in asgs)
    res = api.confirm_assignment(bundle["case"]["id"], asgs[0]["id"], SCHED)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED"


def test_confirm_assignment_not_found(api):
    """PRD §2.6: 'An assignment that exists but does not belong to the case named by
    `caseId` is treated as `ERR_ASSIGNMENT_NOT_FOUND`'."""
    bundle = setup_scheduled_general_case()
    validate_error(
        api.confirm_assignment(bundle["case"]["id"], NON_EXISTENT_UUID, SCHED),
        "ERR_ASSIGNMENT_NOT_FOUND",
    )


# ─── Start case ───────────────────────────────────────────────────────────

def test_start_case_requires_all_assignments_confirmed(api):
    """# difficulty: cross_entity_state_dependency/case_start_depends_on_assignment_confirmation

    PRD §3.6: 'The single precondition is that **every** `CaseAssignment` on the
    case has `status` equal to `CONFIRMED`; if any assignment is still in
    `RESERVED`, the call is rejected with `ERR_ASSIGNMENT_NOT_CONFIRMED`'."""
    bundle = setup_scheduled_case_unconfirmed_for_start()
    validate_error(api.start_case(bundle["case"]["id"], SCHED), "ERR_ASSIGNMENT_NOT_CONFIRMED")


def test_start_case_blocked_state_unchanged(api):
    """# difficulty: cross_entity_state_dependency/case_start_depends_on_assignment_confirmation

    PRD §3.6 (same sentence): when `ERR_ASSIGNMENT_NOT_CONFIRMED` fires, /start is
    rejected — implying the case remains in `SCHEDULED`."""
    bundle = setup_scheduled_case_unconfirmed_for_start()
    api.start_case(bundle["case"]["id"], SCHED)
    case_after = validate_success(api.get_surgical_case(bundle["case"]["id"], SCHED), 200)
    assert case_after["status"] == "SCHEDULED"


def test_start_case_after_confirms_advances_to_in_progress(api):
    """PRD §3.6: 'Surgery start is a `Scheduler`-driven transition from `SCHEDULED`
    to `IN_PROGRESS` ... On success, the system sets the case's `actual_start_minute`
    to the value of `current_minute` at the moment of the call'."""
    bundle = setup_scheduled_general_case()
    confirm_all_assignments(bundle["case"]["id"])
    res = api.start_case(bundle["case"]["id"], SCHED)
    started = validate_success(res, 200)
    assert started["status"] == "IN_PROGRESS"
    assert started["actual_start_minute"] is not None


def test_start_case_in_wrong_state(api):
    """PRD §3.6: 'A request to start a case that is not in `SCHEDULED` is rejected
    with `ERR_CASE_NOT_SCHEDULED`'."""
    case = create_surgical_case(pre_op_assessment_attached=True, informed_consent_verified=True)
    approve_case(case["id"])  # APPROVED, not SCHEDULED
    validate_error(api.start_case(case["id"], SCHED), "ERR_CASE_NOT_SCHEDULED")


# ─── Complete case ───────────────────────────────────────────────────────

def test_complete_case_advances_to_completed(api):
    """PRD §3.6: 'Completion advances the case from `IN_PROGRESS` to `COMPLETED`,
    again driven by a `Scheduler`. ... The system sets the case's `actual_end_minute`
    to the current `current_minute`'."""
    bundle = setup_in_progress_general_case()
    advance_clock(60)  # actual_end will be > actual_start
    res = api.complete_case(bundle["case"]["id"], SCHED)
    completed = validate_success(res, 200)
    assert completed["status"] == "COMPLETED"
    assert completed["actual_end_minute"] is not None
    assert completed["actual_end_minute"] >= completed["actual_start_minute"]


def test_complete_persists_implant_cost_actual(api):
    """PRD §3.6: 'The optional `implant_cost_actual` in the request body is persisted
    onto the case if supplied'."""
    bundle = setup_in_progress_general_case()
    advance_clock(60)
    res = api.complete_case(bundle["case"]["id"], SCHED, payload={"implant_cost_actual": 250.50})
    completed = validate_success(res, 200)
    assert completed["implant_cost_actual"] == 250.50


def test_complete_case_in_wrong_state(api):
    """PRD §3.6: 'A request to complete a case that is not in `IN_PROGRESS` is
    rejected with `ERR_CASE_NOT_IN_PROGRESS`'."""
    bundle = setup_scheduled_general_case()  # SCHEDULED
    validate_error(api.complete_case(bundle["case"]["id"], SCHED), "ERR_CASE_NOT_IN_PROGRESS")


def test_complete_cascades_assignments_to_completed(api):
    """PRD §3.6: 'cascades every `CaseAssignment` for the case from `CONFIRMED` to
    `COMPLETED`'."""
    bundle = setup_in_progress_general_case()
    advance_clock(60)
    complete_case(bundle["case"]["id"])
    asgs = list_assignments_for_case(bundle["case"]["id"])
    assert len(asgs) > 0
    assert all(a["status"] == "COMPLETED" for a in asgs)


def test_complete_flips_instrument_to_soiled(api):
    """PRD §3.6: 'flips the underlying `InstrumentSet`'s `sterilization_status`
    from `CHECKED_OUT` to `SOILED` and sets its `current_case_id` back to `null`'."""
    bundle = setup_in_progress_general_case()
    advance_clock(60)
    complete_case(bundle["case"]["id"])
    inst_after = validate_success(api.get_instrument_set(bundle["instrument"]["id"], SCHED), 200)
    assert inst_after["sterilization_status"] == "SOILED"
    assert inst_after["current_case_id"] is None


# ─── Cyclic instrument state machine — Difficulty Rule 3.2 ────────────────

def test_instrument_full_cycle_state_progression(api):
    """# difficulty: non_linear_state_machine/instrument_set_cyclic_state_machine

    PRD §3.5: 'An instrument set moves through a strict five-state cycle: `SOILED`
    → `IN_STERILIZATION` → `CLEAN_STERILIZED` → `CHECKED_OUT` → `SOILED`'.

    Test traces the cyclic four-state base (omitting the EXPIRED side branch) and
    verifies the snapshot at every waypoint."""
    states = setup_cyclic_instrument_state_machine()
    assert states["instrument_initial"]["sterilization_status"] == "SOILED"
    assert states["instrument_initial"]["cycle_count"] == 0
    assert states["instrument_after_sterilize"]["sterilization_status"] == "CLEAN_STERILIZED"
    assert states["instrument_after_sterilize"]["cycle_count"] == 1
    assert states["instrument_after_schedule"]["sterilization_status"] == "CHECKED_OUT"
    assert states["instrument_after_schedule"]["current_case_id"] == states["case"]["id"]
    assert states["instrument_after_complete"]["sterilization_status"] == "SOILED"
    assert states["instrument_after_complete"]["current_case_id"] is None
    assert states["instrument_after_restart"]["sterilization_status"] == "IN_STERILIZATION"


def test_instrument_cycle_count_increments_on_complete_sterilization(api):
    """# difficulty: non_linear_state_machine/instrument_set_cyclic_state_machine

    PRD §3.5: 'Completion of sterilization advances the set from `IN_STERILIZATION`
    to `CLEAN_STERILIZED`, sets `last_sterilized_at_minute` equal to the value of
    `current_minute` at the moment of completion, increments `cycle_count` by one'."""
    states = setup_cyclic_instrument_state_machine()
    # After one full sterilize cycle, cycle_count == 1
    assert states["instrument_after_sterilize"]["cycle_count"] == 1
    # The cyclic state machine returned to IN_STERILIZATION (loop closed)
    # cycle_count won't increment until the next /complete-sterilization
    assert states["instrument_after_restart"]["cycle_count"] == 1
