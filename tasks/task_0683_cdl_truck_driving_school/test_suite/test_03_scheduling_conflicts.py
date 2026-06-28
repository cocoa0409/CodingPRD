"""Clock-session scheduling: truck/instructor temporal conflicts, class/prereq gating,
and session-state preconditions for complete / cancel / void.

Translates queue A (resource_temporal_overlap/*) and queue B (validations, errors,
state_machines) instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_program, create_truck, create_instructor,
    create_enrollment, create_enrollment_in_training,
    book_session, setup_enrollment_passed,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: resource_temporal_overlap / truck_buffered_overlap_rejected ----

def test_truck_buffered_overlap_rejected():
    """PRD §3.3: "A truck's busy interval is the half-open span beginning at a session's
    starts_at and running through starts_at plus duration_minutes plus the truck's
    turnaround_buffer_minutes; the upper bound is exclusive. A new booking whose own
    half-open interval ... overlaps any existing buffered busy interval on the same
    truck is rejected with ERR_TRUCK_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/truck_buffered_overlap_rejected
    """
    program = create_program()
    truck = create_truck(turnaround_buffer_minutes=30)
    instr1 = create_instructor(full_name="Ivy")
    instr2 = create_instructor(full_name="Jon")
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Session 09:00-10:00 occupies the truck through 10:30 (buffer).
    book_session(eid, "RANGE", instr1["id"], "2026-03-20T09:00:00Z", 60, truck_id=truck["id"])
    # Second session 10:15-11:15 (different instructor) overlaps the buffered tail.
    resp = api_client.create_clock_session(
        eid, {"phase": "RANGE", "instructor_id": instr2["id"], "truck_id": truck["id"],
              "starts_at": "2026-03-20T10:15:00Z", "duration_minutes": 60}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_TRUCK_DOUBLE_BOOKED.value)


def test_truck_buffer_does_not_block_after_buffer_clears():
    """PRD §3.3: "A truck's busy interval is the half-open span beginning at a session's
    starts_at and running through starts_at plus duration_minutes plus the truck's
    turnaround_buffer_minutes; the upper bound is exclusive."

    Design: Difficulty/resource_temporal_overlap/truck_buffered_overlap_rejected
    """
    program = create_program()
    truck = create_truck(turnaround_buffer_minutes=30)
    instr1 = create_instructor(full_name="Ivy")
    instr2 = create_instructor(full_name="Jon")
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Session 09:00-10:00 occupies the truck through 10:30 (exclusive upper bound).
    book_session(eid, "RANGE", instr1["id"], "2026-03-20T09:00:00Z", 60, truck_id=truck["id"])
    # A session starting exactly at 10:30 begins when the buffered interval ends; the
    # upper bound is exclusive, so this is permitted.
    resp = api_client.create_clock_session(
        eid, {"phase": "RANGE", "instructor_id": instr2["id"], "truck_id": truck["id"],
              "starts_at": "2026-03-20T10:30:00Z", "duration_minutes": 60}, REGISTRAR)
    validate_success(resp, expected_status=201)


# ---- Queue A: resource_temporal_overlap / instructor_unbuffered_overlap_rejected_adjacency_ok ----

def test_instructor_unbuffered_overlap_rejected():
    """PRD §3.3: "An instructor's busy interval is the half-open span from starts_at
    through starts_at plus duration_minutes with no turnaround buffer; a new session
    overlapping the instructor's existing BOOKED interval is rejected with
    ERR_INSTRUCTOR_DOUBLE_BOOKED".

    Design: Difficulty/resource_temporal_overlap/instructor_unbuffered_overlap_rejected_adjacency_ok
    """
    program = create_program()
    instructor = create_instructor(full_name="Ivy")
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Ivy booked 09:00-10:00.
    book_session(eid, "CLASSROOM", instructor["id"], "2026-03-20T09:00:00Z", 60)
    # 09:30-10:30 overlaps Ivy's existing interval.
    resp = api_client.create_clock_session(
        eid, {"phase": "CLASSROOM", "instructor_id": instructor["id"],
              "starts_at": "2026-03-20T09:30:00Z", "duration_minutes": 60}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED.value)


def test_instructor_back_to_back_adjacency_allowed():
    """PRD §3.3: "because the intervals are half-open, a back-to-back session that begins
    exactly when the prior one ends is permitted."

    Design: Difficulty/resource_temporal_overlap/instructor_unbuffered_overlap_rejected_adjacency_ok
    """
    program = create_program()
    instructor = create_instructor(full_name="Ivy")
    eid, _, _ = create_enrollment_in_training(program["id"])
    book_session(eid, "CLASSROOM", instructor["id"], "2026-03-20T09:00:00Z", 60)
    # 10:00-11:00 begins exactly when the prior session ends; no buffer for instructors.
    resp = api_client.create_clock_session(
        eid, {"phase": "CLASSROOM", "instructor_id": instructor["id"],
              "starts_at": "2026-03-20T10:00:00Z", "duration_minutes": 60}, REGISTRAR)
    validate_success(resp, expected_status=201)


# ---- Queue B: validations / errors / state_machines ----

def test_classroom_session_with_truck_rejected():
    """PRD §3.3: "a CLASSROOM session must not supply a truck_id, and supplying one is
    rejected with ERR_TRUCK_CLASS_MISMATCH."

    Design: Corner/validations/classroom_session_with_truck_rejected
    """
    program = create_program()
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    resp = api_client.create_clock_session(
        eid, {"phase": "CLASSROOM", "instructor_id": instructor["id"], "truck_id": truck["id"],
              "starts_at": "2026-03-20T09:00:00Z", "duration_minutes": 60}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_TRUCK_CLASS_MISMATCH.value)


def test_book_session_before_prereqs_met_rejected():
    """PRD §3.3: "a session may only be booked when the enrollment is in TRAINING (which
    means both DOT-medical and permit are verified). Attempting to book while the
    enrollment is in any other status is rejected with ERR_PREREQ_NOT_MET."

    Design: Corner/validations/book_session_before_prereqs_met_rejected
    """
    program = create_program()
    instructor = create_instructor()
    enr = create_enrollment(program["id"])  # APPLIED, no prereqs
    resp = api_client.create_clock_session(
        enr["id"],
        {"phase": "CLASSROOM", "instructor_id": instructor["id"],
         "starts_at": "2026-03-20T09:00:00Z", "duration_minutes": 60}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_PREREQ_NOT_MET.value)


def test_invalid_request_zero_duration_rejected():
    """PRD §2.8: "a duration_minutes that is not greater than zero ... yields
    ERR_INVALID_REQUEST." PRD §3.3: "the duration_minutes scheduled length (which must
    be greater than zero)".

    Design: Corner/errors/invalid_request_negative_duration_rejected
    """
    program = create_program()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    resp = api_client.create_clock_session(
        eid, {"phase": "CLASSROOM", "instructor_id": instructor["id"],
              "starts_at": "2026-03-20T09:00:00Z", "duration_minutes": 0}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_complete_session_before_elapsed_rejected():
    """PRD §3.3: "enough time has elapsed on the clock — specifically that starts_at
    plus duration_minutes is at or before the current clock time (otherwise
    ERR_SESSION_NOT_ELAPSED)."

    Design: Corner/state_machines/complete_session_before_elapsed_rejected
    """
    program = create_program()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    # Clock default is 2026-04-01; this session is in the future.
    sess = book_session(eid, "CLASSROOM", instructor["id"], "2026-05-01T09:00:00Z", 60)
    resp = api_client.complete_clock_session(sess["id"], make_instructor_headers(instructor["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ELAPSED.value)


def test_cancel_already_cancelled_session_invalid_state():
    """PRD §2.8: "if the target resource is not in a state from which the requested
    transition is defined, the request yields ERR_INVALID_STATE." PRD §3.3: "A session
    is terminal once COMPLETED or CANCELLED."

    Design: Corner/state_machines/cancel_already_cancelled_session_invalid_state
    """
    program = create_program()
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "RANGE", instructor["id"], "2026-03-20T09:00:00Z", 60,
                        truck_id=truck["id"])
    instr_headers = make_instructor_headers(instructor["id"])
    validate_success(api_client.cancel_clock_session(sess["id"], instr_headers))
    # Second cancel on the already-CANCELLED session.
    resp = api_client.cancel_clock_session(sess["id"], instr_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_void_completed_session_after_passed_rejected():
    """PRD §3.3: "This void is permitted only when the session is COMPLETED and the
    enrollment is neither PASSED nor COMPLETED; once the enrollment has reached either
    of those, the void is rejected with ERR_SESSION_LOCKED."

    Design: Corner/state_machines/void_completed_session_after_passed_rejected
    """
    # Drive to PASSED via a single ROAD session (road_required 1, others 0).
    ctx = setup_enrollment_passed(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1)
    road_session = ctx["sessions"]["ROAD"]
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["status"] == "PASSED"
    # Administratively voiding the COMPLETED road session now is locked.
    resp = api_client.cancel_clock_session(road_session["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SESSION_LOCKED.value)
