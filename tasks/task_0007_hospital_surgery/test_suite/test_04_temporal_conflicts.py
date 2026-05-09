"""Temporal-conflict gates: room turnover buffer, staff time, instrument time."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_schedule_payload,
    make_staff_assignment,
    setup_room_buffer_boundary,
    setup_staff_overlap_boundary,
    create_surgical_case,
    approve_case,
    create_operating_room,
    create_anesthesiologist,
    create_instrument_set,
    schedule_case,
)


SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty Rule 8.1 — Room turnover buffer closed-gap semantics ──────

def test_room_buffer_at_boundary_passes(api):
    """# difficulty: resource_temporal_overlap/room_turnover_buffer_closed_gap_semantics

    PRD §3.4: 'Boundary semantics are closed-gap: the test that **passes** is when
    the existing case's `planned_end_minute` plus the room's `turnover_buffer_minutes`
    is less than or equal to the new case's `planned_start_minute`.'

    Existing C1 ends at 120 with 30-min buffer → R clears at 150. New start at
    150 (= 120+30) is exactly the closed-gap boundary, so it passes."""
    bundle = setup_room_buffer_boundary()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=150,
        planned_end_minute=210,
        staff_assignments=[
            make_staff_assignment(bundle["anesth_for_c2_pass"]["id"], "LEAD_ANESTHESIOLOGIST")
        ],
        instrument_set_id=bundle["instrument_for_c2_pass"]["id"],
    )
    res = api.schedule_case(bundle["case_c2_pass_approved"]["id"], payload, SCHED)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_room_buffer_just_inside_rejects(api):
    """# difficulty: resource_temporal_overlap/room_turnover_buffer_closed_gap_semantics

    PRD §3.4: 'If exactly that boundary holds, the schedule succeeds; if the existing
    case's end-plus-buffer crosses the new case's start by even one minute, the
    schedule fails.'

    Existing C1 occupies [0, 150) including buffer; new start at 149 fails with
    `ERR_ROOM_TIME_CONFLICT`."""
    bundle = setup_room_buffer_boundary()
    payload = create_schedule_payload(
        scheduled_room_id=bundle["room"]["id"],
        planned_start_minute=149,
        planned_end_minute=209,
        staff_assignments=[
            make_staff_assignment(bundle["anesth_for_c2_fail"]["id"], "LEAD_ANESTHESIOLOGIST")
        ],
        instrument_set_id=bundle["instrument_for_c2_fail"]["id"],
    )
    validate_error(
        api.schedule_case(bundle["case_c2_fail_approved"]["id"], payload, SCHED),
        "ERR_ROOM_TIME_CONFLICT",
    )


# ─── Difficulty Rule 8.2 — Staff half-open overlap (no buffer) ────────────

def test_staff_adjacent_intervals_allowed(api):
    """# difficulty: resource_temporal_overlap/staff_open_half_overlap_no_buffer

    PRD §3.4: 'The **staff-time conflict** check rejects the schedule when any
    requested staff member already has a `CaseAssignment` whose `status` is
    `RESERVED` or `CONFIRMED` and whose half-open interval
    `[assigned_start_minute, assigned_end_minute)` overlaps the new case's planned
    half-open interval `[planned_start_minute, planned_end_minute)`.'

    Adjacency [0,60) and [60,120) on the same staff is touching, not overlapping —
    half-open semantics admit it."""
    bundle = setup_staff_overlap_boundary()
    r1, r2, r3 = bundle["rooms"]
    inst1, inst2, inst3 = bundle["instruments"]
    payload = create_schedule_payload(
        scheduled_room_id=r2["id"],
        planned_start_minute=60,
        planned_end_minute=120,
        staff_assignments=[make_staff_assignment(bundle["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst2["id"],
    )
    res = api.schedule_case(bundle["case_c2_adj_pass_approved"]["id"], payload, SCHED)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_staff_overlap_one_minute_rejected(api):
    """# difficulty: resource_temporal_overlap/staff_open_half_overlap_no_buffer

    PRD §3.4 (same sentence as above): half-open intervals overlap when
    `[0,60)` and `[59,120)` are scheduled to the same staff — the error is
    `ERR_STAFF_TIME_CONFLICT`."""
    bundle = setup_staff_overlap_boundary()
    r1, r2, r3 = bundle["rooms"]
    inst1, inst2, inst3 = bundle["instruments"]
    payload = create_schedule_payload(
        scheduled_room_id=r3["id"],
        planned_start_minute=59,
        planned_end_minute=120,
        staff_assignments=[make_staff_assignment(bundle["anesth"]["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=inst3["id"],
    )
    validate_error(
        api.schedule_case(bundle["case_c2_overlap_fail_approved"]["id"], payload, SCHED),
        "ERR_STAFF_TIME_CONFLICT",
    )


# ─── Instrument-time conflict ─────────────────────────────────────────────

def test_instrument_time_conflict(api):
    """PRD §3.4: 'The **instrument-time conflict** check rejects the schedule when
    the requested instrument set already has an `InstrumentBooking` whose `status`
    is `RESERVED` or `CHECKED_OUT` and whose owning case's planned half-open
    interval overlaps the new case's planned half-open interval; the error
    returned is `ERR_INSTRUMENT_TIME_CONFLICT`'.

    Note: the booked instrument set's sterilization_status flips to CHECKED_OUT on
    the first schedule (per §3.4 cascade), so a second schedule against the same
    set on an overlapping window naturally fails the priority-5 state check first.
    The PRD does not commit to a specific surfaced error in this race, so this
    test allows either ERR_INSTRUMENT_NOT_STERILIZED or ERR_INSTRUMENT_TIME_CONFLICT.
    """
    from test_helpers import validate_error_is_one_of
    room1 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    room2 = create_operating_room(specialty_required="GENERAL", hourly_rate=500.00)
    a1 = create_anesthesiologist()
    a2 = create_anesthesiologist()
    instrument = create_instrument_set(specialty="GENERAL", sterilize=True)
    c1 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c2 = approve_case(create_surgical_case(specialty_required="GENERAL")["id"])
    c1 = schedule_case(
        c1["id"],
        room_id=room1["id"],
        planned_start_minute=0,
        planned_end_minute=60,
        staff_assignments=[make_staff_assignment(a1["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    payload = create_schedule_payload(
        scheduled_room_id=room2["id"],
        planned_start_minute=30,
        planned_end_minute=90,
        staff_assignments=[make_staff_assignment(a2["id"], "LEAD_ANESTHESIOLOGIST")],
        instrument_set_id=instrument["id"],
    )
    res = api.schedule_case(c2["id"], payload, SCHED)
    validate_error_is_one_of(
        res, ["ERR_INSTRUMENT_NOT_STERILIZED", "ERR_INSTRUMENT_TIME_CONFLICT"]
    )
