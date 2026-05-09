"""Scheduling gates: specialty, qualifications, shift, role, working hours."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_surgical_case,
    approve_case,
    create_operating_room,
    create_anesthesiologist,
    create_scrub_nurse,
    create_instrument_set,
    schedule_case,
    create_schedule_payload,
    make_staff_assignment,
    setup_basic_general_environment,
    setup_state_vs_safety_qual_conflict,
    setup_safety_vs_temporal_conflict,
    setup_working_hours_boundary_environment,
    setup_unsterilized_instrument_for_schedule,
)


SCHED = TEST_USERS["scheduler_headers"]


def _approved_general_case():
    case = create_surgical_case(specialty_required="GENERAL")
    return approve_case(case["id"])


def _approved_cardiac_case():
    case = create_surgical_case(specialty_required="CARDIAC")
    return approve_case(case["id"])


# ─── State precondition: case must be APPROVED for /schedule ──────────────

def test_schedule_requires_case_in_approved(api):
    """PRD §3.4: 'A request to schedule a case whose `status` is not `APPROVED`
    is rejected with `ERR_CASE_NOT_APPROVED`'."""
    case = create_surgical_case()  # REQUESTED
    env = setup_basic_general_environment()
    payload = create_schedule_payload(
        scheduled_room_id=env["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(env["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=env["instrument"]["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_CASE_NOT_APPROVED")


# ─── Specialty mismatches ─────────────────────────────────────────────────

def test_schedule_room_specialty_mismatch(api):
    """PRD §3.3: 'The room must serve the case's specialty: the room's
    `specialty_required` must equal the case's `specialty_required`, and a
    mismatch is rejected with `ERR_ROOM_SPECIALTY_RESTRICTED`'."""
    cardiac_room = create_operating_room(
        room_type="CARDIAC_OR", specialty_required="CARDIAC", hourly_rate=1000.00
    )
    anesth = create_anesthesiologist(qualifications=["GENERAL"])
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = _approved_general_case()
    payload = create_schedule_payload(
        scheduled_room_id=cardiac_room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_ROOM_SPECIALTY_RESTRICTED")


def test_schedule_instrument_specialty_mismatch(api):
    """PRD §3.5: 'When the set's `specialty` does not equal the case's
    `specialty_required`, the call is rejected with `ERR_INSTRUMENT_SPECIALTY_MISMATCH`'."""
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    anesth = create_anesthesiologist(qualifications=["GENERAL"])
    cardiac_inst = create_instrument_set(specialty="CARDIAC", sterilize=True)
    case = _approved_general_case()
    payload = create_schedule_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=cardiac_inst["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_INSTRUMENT_SPECIALTY_MISMATCH")


# ─── Staff qualification ──────────────────────────────────────────────────

def test_staff_qualification_mismatch(api):
    """PRD §3.3: 'Every requested staff member must list the case's `specialty_required`
    among their `qualifications`; any staff member who does not is rejected with
    `ERR_QUALIFICATION_MISMATCH`'."""
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    cardiac_only_staff = create_anesthesiologist(qualifications=["CARDIAC"])
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = _approved_general_case()
    payload = create_schedule_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(cardiac_only_staff["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_QUALIFICATION_MISMATCH")


# ─── Staff shift coverage ─────────────────────────────────────────────────

def test_staff_out_of_shift(api):
    """PRD §3.3: 'Every requested staff member's shift window must fully cover the
    planned interval — the staff member's `shift_start_minute` must be less than or
    equal to `planned_start_minute` and their `shift_end_minute` must be greater
    than or equal to `planned_end_minute`; a violation is rejected with
    `ERR_STAFF_OUT_OF_SHIFT`'."""
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    short_shift_staff = create_anesthesiologist(
        qualifications=["GENERAL"], shift_start=0, shift_end=30
    )
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = _approved_general_case()
    payload = create_schedule_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,  # shift ends at 30, but case ends at 60
        staff_assignments=[make_staff_assignment(short_shift_staff["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_STAFF_OUT_OF_SHIFT")


# ─── Staff role compatibility ────────────────────────────────────────────

def test_staff_role_mismatch(api):
    """PRD §3.3: 'Every staff member's `role_in_case` must be compatible with their
    `staff_role`: a `LEAD_ANESTHESIOLOGIST` requires the staff member to be an
    `ANESTHESIOLOGIST` ... any other pairing is rejected with `ERR_STAFF_ROLE_MISMATCH`'."""
    room = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    scrub_nurse = create_scrub_nurse(qualifications=["GENERAL"])
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    case = _approved_general_case()
    payload = create_schedule_payload(
        scheduled_room_id=room["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        # SCRUB_NURSE staff with LEAD_ANESTHESIOLOGIST role_in_case
        staff_assignments=[make_staff_assignment(scrub_nurse["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    validate_error(api.schedule_case(case["id"], payload, SCHED), "ERR_STAFF_ROLE_MISMATCH")


# ─── Working hours boundary (Difficulty Rule 6, instance 6.2) ─────────────

def test_working_hours_at_boundary_720_passes(api):
    """# difficulty: boundary_precision_check/staff_working_hours_720_boundary_on_schedule

    PRD §3.3: 'If the resulting sum exceeds 720 minutes, the request is rejected
    with `ERR_STAFF_WORKING_HOURS_EXCEEDED` (HTTP 422); if the resulting sum is
    less than or equal to 720 minutes, the cap is satisfied. The boundary is
    therefore strict on the upper side — exactly 720 minutes including the new
    schedule passes; 721 minutes does not.'"""
    env = setup_working_hours_boundary_environment()
    r1, r2, r3 = env["rooms"]
    inst1, inst2, inst3 = env["instruments"]
    anesth = env["anesth"]
    c2 = env["case_c2_approved"]

    # Schedule c2 600..720 — A's window-total = 600 + 120 = 720 (≤ 720, pass)
    payload = create_schedule_payload(
        scheduled_room_id=r2["id"],
        planned_start_minute=600,
        planned_end_minute=720,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst2["id"],
    )
    res = api.schedule_case(c2["id"], payload, SCHED)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_working_hours_above_boundary_721_rejected(api):
    """# difficulty: boundary_precision_check/staff_working_hours_720_boundary_on_schedule

    PRD §3.3: '... 721 minutes does not.' (strict upper boundary; total > 720
    rejects with `ERR_STAFF_WORKING_HOURS_EXCEEDED`)."""
    env = setup_working_hours_boundary_environment()
    r1, r2, r3 = env["rooms"]
    inst1, inst2, inst3 = env["instruments"]
    anesth = env["anesth"]
    c2 = env["case_c2_approved"]
    c3 = env["case_c3_approved"]

    # First land C2 at 600..720 to use up A to exactly the 720 cap
    p2 = create_schedule_payload(
        scheduled_room_id=r2["id"],
        planned_start_minute=600,
        planned_end_minute=720,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst2["id"],
    )
    validate_success(api.schedule_case(c2["id"], p2, SCHED), 200)

    # Now C3 720..841 — A's window-total = 720 + 121 = 841 (>720, reject)
    p3 = create_schedule_payload(
        scheduled_room_id=r1["id"],
        planned_start_minute=720,
        planned_end_minute=841,
        staff_assignments=[make_staff_assignment(anesth["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst3["id"],
    )
    validate_error(api.schedule_case(c3["id"], p3, SCHED), "ERR_STAFF_WORKING_HOURS_EXCEEDED")


# ─── Validation priority — Difficulty Rule 5 ──────────────────────────────

def test_priority_state_wins_over_safety_qualification(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_qualification

    PRD §2.6: priority ladder evaluates `5. The state of the target entity for
    state-transition operations` before `7. Business safety preconditions in this
    internal sequence: pre-operative assessment attachment ... staff qualifications
    (`ERR_QUALIFICATION_MISMATCH`)`. State-error must surface first when both
    apply.

    PRD §3.4: '... a case whose `status` is not `APPROVED` is rejected with
    `ERR_CASE_NOT_APPROVED`'."""
    bundle = setup_state_vs_safety_qual_conflict()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(bundle["staff"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=bundle["instrument"]["id"],
    )
    validate_error(api.schedule_case(bundle["case"]["id"], payload, SCHED), "ERR_CASE_NOT_APPROVED")


def test_priority_safety_qualification_wins_over_temporal_room(api):
    """# difficulty: priority_pair_validation_conflict/business_safety_qualification_vs_business_temporal_room

    PRD §2.6: priority ladder evaluates `7. Business safety preconditions ... staff
    qualifications (`ERR_QUALIFICATION_MISMATCH`)` before `9. Temporal conflicts in
    this internal sequence: room turnover-buffer overlap (`ERR_ROOM_TIME_CONFLICT`)`.
    Qualification-error must surface first when both apply."""
    bundle = setup_safety_vs_temporal_conflict()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        # MismatchStaff has [GENERAL] but case is CARDIAC; ALSO room is busy [0,150)
        staff_assignments=[
            make_staff_assignment(bundle["mismatch_staff"]["id"], "LEAD_ANESTHESIOLOGIST")
        ],
        instrument_set_id=bundle["instrument_for_c1"]["id"],
    )
    validate_error(
        api.schedule_case(bundle["case_c1_approved"]["id"], payload, SCHED),
        "ERR_QUALIFICATION_MISMATCH",
    )


def test_priority_state_rejection_leaves_case_in_requested(api):
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_qualification

    PRD §3.2: case state advances on `/approve` only — `/schedule` does not advance
    a `REQUESTED` case. PRD §3.4: 'A request to schedule a case whose `status` is
    not `APPROVED` is rejected with `ERR_CASE_NOT_APPROVED`'. A rejected /schedule
    must therefore leave the case in `REQUESTED`."""
    bundle = setup_state_vs_safety_qual_conflict()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(bundle["staff"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=bundle["instrument"]["id"],
    )
    api.schedule_case(bundle["case"]["id"], payload, SCHED)  # rejected per the priority pair test
    case_after = validate_success(api.get_surgical_case(bundle["case"]["id"], SCHED), 200)
    assert case_after["status"] == "REQUESTED"


def test_priority_safety_rejection_leaves_case_in_approved(api):
    """# difficulty: priority_pair_validation_conflict/business_safety_qualification_vs_business_temporal_room

    PRD §3.4: 'A request to schedule a case whose `status` is not `APPROVED` is
    rejected with `ERR_CASE_NOT_APPROVED`' — implying a rejected schedule leaves
    the case in `APPROVED` (not advanced). Following the qualification-wins
    decision above, a /schedule that fails ERR_QUALIFICATION_MISMATCH must
    likewise not advance the case."""
    bundle = setup_safety_vs_temporal_conflict()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[
            make_staff_assignment(bundle["mismatch_staff"]["id"], "LEAD_ANESTHESIOLOGIST")
        ],
        instrument_set_id=bundle["instrument_for_c1"]["id"],
    )
    api.schedule_case(bundle["case_c1_approved"]["id"], payload, SCHED)
    case_after = validate_success(api.get_surgical_case(bundle["case_c1_approved"]["id"], SCHED), 200)
    assert case_after["status"] == "APPROVED"


# ─── Instrument-not-sterilized — Difficulty Rule 7.1 ──────────────────────

def test_schedule_blocked_by_unsterilized_instrument(api):
    """# difficulty: cross_entity_state_dependency/case_schedule_depends_on_instrument_sterilization

    PRD §3.5: 'A scheduling attempt against an instrument set in any non-clean state
    surfaces a precise reason. When the set is `SOILED`, `IN_STERILIZATION`, or
    `CHECKED_OUT`, the call is rejected with `ERR_INSTRUMENT_NOT_STERILIZED`'."""
    bundle = setup_unsterilized_instrument_for_schedule()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(bundle["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=bundle["instrument"]["id"],  # SOILED
    )
    validate_error(api.schedule_case(bundle["case"]["id"], payload, SCHED), "ERR_INSTRUMENT_NOT_STERILIZED")


def test_unsterilized_schedule_does_not_advance_case(api):
    """# difficulty: cross_entity_state_dependency/case_schedule_depends_on_instrument_sterilization

    PRD §3.4: 'A request to schedule a case whose `status` is not `APPROVED` is
    rejected with `ERR_CASE_NOT_APPROVED`' — implies a rejected schedule leaves
    the case in APPROVED. PRD §3.5: 'When the set is `SOILED`, `IN_STERILIZATION`,
    or `CHECKED_OUT`, the call is rejected with `ERR_INSTRUMENT_NOT_STERILIZED`'."""
    bundle = setup_unsterilized_instrument_for_schedule()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(bundle["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=bundle["instrument"]["id"],
    )
    api.schedule_case(bundle["case"]["id"], payload, SCHED)
    case_after = validate_success(api.get_surgical_case(bundle["case"]["id"], SCHED), 200)
    assert case_after["status"] == "APPROVED"
