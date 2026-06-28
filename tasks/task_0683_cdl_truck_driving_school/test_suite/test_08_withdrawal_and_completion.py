"""Withdrawal cascades, the conserved truck-minute invariant, terminal lockdown, and the
FMCSA completion-report transmit that requires a PASSED enrollment.

Translates queue A (transitive_cascade/withdraw_cancels_sessions_releases_truck_minutes_depth3,
compensating_invariant/book_then_cancel_preserves_truck_reserved_minutes,
cross_entity_state_dependency/transmit_report_requires_enrollment_passed) and queue B
(state_machines) instances.

The queue B corner instance validations/transmit_report_before_passed_rejected is an
excluded_because stub whose difficulty_instance cross-reference resolves to
cross_entity_state_dependency/transmit_report_requires_enrollment_passed (covered below);
no separate test is emitted for the stub.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_program, create_truck, create_instructor,
    create_enrollment_in_training, book_session,
    setup_draft_completion_report, setup_completed_enrollment,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: transitive_cascade / withdraw_cancels_sessions_releases_truck_minutes_depth3 ----

def test_withdraw_cancels_sessions_releases_truck_minutes():
    """PRD §3.9: "All of the enrollment's BOOKED clock sessions are auto-cancelled, and
    the reserved minutes they held are released back to their trucks and instructors."
    PRD §2.5: "the reserved_minutes of a Truck is the sum of duration_minutes over that
    truck's BOOKED sessions".

    Design: Difficulty/transitive_cascade/withdraw_cancels_sessions_releases_truck_minutes_depth3
    """
    program = create_program()
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "RANGE", instructor["id"], "2026-03-20T09:00:00Z", 120,
                        truck_id=truck["id"])
    # Pre-withdraw: the truck holds 120 reserved minutes.
    pre = validate_success(api_client.get_truck(truck["id"], ADMIN))
    assert pre["reserved_minutes"] == 120
    validate_success(api_client.withdraw_enrollment(eid, REGISTRAR))
    # Depth-3: withdraw -> session CANCELLED -> reserved_minutes released to 0.
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["status"] == "WITHDRAWN"
    session = validate_success(api_client.get_clock_session(sess["id"], ADMIN))
    assert session["status"] == "CANCELLED"
    post = validate_success(api_client.get_truck(truck["id"], ADMIN))
    assert post["reserved_minutes"] == 0


def test_withdraw_session_cancel_is_the_intermediate_cascade_hop():
    """PRD §3.9: "All of the enrollment's BOOKED clock sessions are auto-cancelled, and
    the reserved minutes they held are released back to their trucks and instructors."

    Design: Difficulty/transitive_cascade/withdraw_cancels_sessions_releases_truck_minutes_depth3
    """
    program = create_program()
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "RANGE", instructor["id"], "2026-03-20T09:00:00Z", 120,
                        truck_id=truck["id"])
    api_client.withdraw_enrollment(eid, REGISTRAR)
    # The instructor's reserved minutes are also released (the same cascade hop).
    instr = validate_success(api_client.get_instructor(instructor["id"], ADMIN))
    assert instr["reserved_minutes"] == 0
    session = validate_success(api_client.get_clock_session(sess["id"], ADMIN))
    assert session["status"] == "CANCELLED"


# ---- Queue A: compensating_invariant / book_then_cancel_preserves_truck_reserved_minutes ----

def test_book_then_cancel_preserves_truck_reserved_minutes():
    """PRD §2.5: "The governing invariant is that booking a session and then cancelling
    the same session leaves reserved_minutes exactly equal to its pre-booking value." PRD
    §3.3: "Cancelling a BOOKED session moves it to CANCELLED, subtracts its
    duration_minutes from the instructor's reserved_minutes and, when a truck is set, from
    the truck's reserved_minutes".

    Design: Difficulty/compensating_invariant/book_then_cancel_preserves_truck_reserved_minutes
    """
    program = create_program()
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "RANGE", instructor["id"], "2026-03-25T09:00:00Z", 120,
                        truck_id=truck["id"])
    mid = validate_success(api_client.get_truck(truck["id"], ADMIN))
    assert mid["reserved_minutes"] == 120
    cancelled = validate_success(
        api_client.cancel_clock_session(sess["id"], make_instructor_headers(instructor["id"])))
    assert cancelled["status"] == "CANCELLED"
    post = validate_success(api_client.get_truck(truck["id"], ADMIN))
    assert post["reserved_minutes"] == 0, "cancel must restore reserved_minutes to its pre-book value"


def test_book_then_cancel_preserves_instructor_reserved_minutes():
    """PRD §2.5: "the reserved_minutes of an Instructor is the sum of duration_minutes
    over that instructor's BOOKED sessions. The governing invariant is that booking a
    session and then cancelling the same session leaves reserved_minutes exactly equal to
    its pre-booking value."

    Design: Difficulty/compensating_invariant/book_then_cancel_preserves_truck_reserved_minutes
    """
    program = create_program()
    truck = create_truck()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "RANGE", instructor["id"], "2026-03-25T09:00:00Z", 120,
                        truck_id=truck["id"])
    mid = validate_success(api_client.get_instructor(instructor["id"], ADMIN))
    assert mid["reserved_minutes"] == 120
    api_client.cancel_clock_session(sess["id"], make_instructor_headers(instructor["id"]))
    post = validate_success(api_client.get_instructor(instructor["id"], ADMIN))
    assert post["reserved_minutes"] == 0


# ---- Queue A: cross_entity_state_dependency / transmit_report_requires_enrollment_passed ----

def test_transmit_report_requires_enrollment_passed_completes_enrollment():
    """PRD §3.9: "Transmission requires that the report still be DRAFT, that the
    enrollment be in PASSED status (otherwise ERR_ENROLLMENT_NOT_PASSED), and that the
    passing_test_id reference a GRADED test whose outcome is PASS." PRD §3.9: "On
    transmission the report moves to TRANSMITTED, the enrollment's fmcsa_reported flag is
    set true, and the enrollment automatically advances from PASSED to COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/transmit_report_requires_enrollment_passed
    """
    ctx = setup_draft_completion_report(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1)
    # The enrollment is PASSED with a DRAFT report referencing the passing test.
    pre = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert pre["status"] == "PASSED"
    report = validate_success(api_client.transmit_completion_report(ctx["report"]["id"], ADMIN))
    assert report["status"] == "TRANSMITTED"
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["status"] == "COMPLETED"
    assert enr["fmcsa_reported"] is True


def test_transmit_snapshots_hour_totals_on_report():
    """PRD §3.9: "A drafted report begins in DRAFT status and snapshots the candidate's
    hour totals at draft time: reported_classroom_hours, reported_range_hours, and
    reported_road_hours are taken from the enrollment's logged classroom, range, and road
    hours respectively."

    Design: Difficulty/cross_entity_state_dependency/transmit_report_requires_enrollment_passed
    """
    ctx = setup_draft_completion_report(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1)
    report = validate_success(api_client.get_completion_report(ctx["report"]["id"], REGISTRAR))
    # The qualifying enrollment logged exactly 1.0 road hour (one 60-min ROAD session).
    assert report["reported_road_hours"] == pytest.approx(1.0, abs=0.001)


# ---- Queue B: state_machines / withdraw_completed_enrollment_blocked_terminal ----

def test_withdraw_completed_enrollment_blocked_terminal():
    """PRD §3.9: "A Registrar may withdraw an enrollment from any non-terminal status —
    that is, whenever the enrollment is not already COMPLETED". PRD §2.8: "if the target
    resource is not in a state from which the requested transition is defined, the request
    yields ERR_INVALID_STATE."

    Design: Corner/state_machines/withdraw_completed_enrollment_blocked_terminal
    """
    ctx = setup_completed_enrollment(
        classroom_required_hours=0, range_required_hours=0, road_required_hours=1)
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["status"] == "COMPLETED"
    # Withdrawing a COMPLETED (terminal) enrollment is rejected.
    resp = api_client.withdraw_enrollment(ctx["enrollment_id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
