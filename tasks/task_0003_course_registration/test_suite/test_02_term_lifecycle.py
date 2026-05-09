"""Term lifecycle: PLANNING → REGISTRATION_OPEN → REGISTRATION_CLOSED →
IN_SESSION → CONCLUDED. Plus the cascade from REGISTRATION_OPEN →
REGISTRATION_CLOSED and the conclude precondition.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    create_term_payload,
)
from test_helpers.fixtures import (
    advance_clock, create_term_in_planning, setup_basic_world,
    setup_open_offering, submit_enrollment_success, get_offering,
    get_enrollment_request, list_waitlist, settle_tuition,
    setup_offering_with_seat_taken,
)


def test_term_created_in_planning(api, registrar_headers):
    """PRD §3.1: "A Registrar creates a term in PLANNING by supplying a unique
    code, the four time anchors registration_open_at, registration_close_at,
    classes_start_at, and exam_window_start_at, and the closing
    exam_window_end_at."

    Claim: POST /terms returns status=PLANNING.
    """
    term = create_term_in_planning()
    assert term["status"] == "PLANNING"


def test_term_auto_transitions_to_registration_open(api, registrar_headers):
    """PRD §3.1: "The first three transitions are time-driven and fire
    automatically as the logical clock reaches each anchor. The transition
    PLANNING → REGISTRATION_OPEN carries no side effects beyond the status
    change."

    Claim: advancing clock to registration_open_at moves the term to
    REGISTRATION_OPEN.
    """
    term = create_term_in_planning()
    assert term["status"] == "PLANNING"
    advance_clock(term["registration_open_at"])
    refreshed = validate_success(
        api.get_term(term["id"], registrar_headers), 200
    )
    assert refreshed["status"] == "REGISTRATION_OPEN"


def test_term_auto_transitions_with_cascade_on_close(api, registrar_headers):
    """PRD §3.1: "The transition REGISTRATION_OPEN → REGISTRATION_CLOSED is the
    most consequential of the auto-transitions: every EnrollmentRequest that
    is still in SUBMITTED is moved to REJECTED (the rejection is recorded as
    having occurred because registration closed), and every WaitlistEntry
    whose status is still ACTIVE is moved to EXPIRED."

    Claim: when the term advances to REGISTRATION_CLOSED, an ACTIVE
    WaitlistEntry on a child offering becomes EXPIRED.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world)
    waitlisted = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert waitlisted["academic_status"] == "WAITLISTED"

    # Advance the clock past registration_close_at.
    advance_clock(world["term"]["registration_close_at"])

    refreshed_term = validate_success(api.get_term(world["term"]["id"], registrar_headers), 200)
    assert refreshed_term["status"] == "REGISTRATION_CLOSED"

    waitlist_entries = list_waitlist(full["offering"]["id"])
    # All ACTIVE entries should be EXPIRED now.
    for e in waitlist_entries:
        assert e["status"] != "ACTIVE", (
            f"Expected no ACTIVE waitlist entries after term close; got {e}"
        )


def test_term_conclude_rejected_before_exam_window_end(api, registrar_headers):
    """PRD §3.1: "the request is rejected with ERR_TERM_NOT_READY_FOR_CONCLUDE
    unless the logical clock has reached exam_window_end_at (lower-bound
    inclusive)."

    Claim: POST /terms/{id}/conclude before exam_window_end_at → ERR_TERM_NOT_READY_FOR_CONCLUDE.
    """
    world = setup_basic_world()
    # Drive the term forward to IN_SESSION but stop before exam_window_end_at.
    advance_clock(world["term"]["classes_start_at"])
    refreshed = validate_success(api.get_term(world["term"]["id"], registrar_headers), 200)
    assert refreshed["status"] == "IN_SESSION"
    res = api.conclude_term(world["term"]["id"], registrar_headers)
    validate_error(res, "ERR_TERM_NOT_READY_FOR_CONCLUDE")


def test_term_conclude_settles_paid_enrollments(api, registrar_headers, finance_headers):
    """PRD §3.1: "On a successful conclusion, every APPROVED EnrollmentRequest
    whose financial_status is PAID advances to SETTLED and has its
    final_credit_charge populated."

    Claim: After conclude, an APPROVED+PAID enrollment moves to SETTLED.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"
    assert er["financial_status"] == "BILLED"
    settle_tuition(er["id"])

    advance_clock(world["term"]["exam_window_end_at"])
    res = api.conclude_term(world["term"]["id"], registrar_headers)
    validate_success(res, 200)

    er_final = get_enrollment_request(er["id"])
    assert er_final["academic_status"] == "SETTLED"
    assert er_final["financial_status"] == "PAID"
    assert er_final["final_credit_charge"] is not None


def test_term_conclude_rejects_unpaid_approved_enrollments(api, registrar_headers):
    """PRD §3.1: "every APPROVED enrollment whose financial_status is not PAID
    is moved to REJECTED (recorded as canceled because tuition was unpaid)."

    Claim: an APPROVED+BILLED (not PAID) enrollment is moved to REJECTED on
    term conclude.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0, base_capacity=5,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"
    assert er["financial_status"] == "BILLED"
    # Do NOT settle tuition.

    advance_clock(world["term"]["exam_window_end_at"])
    res = api.conclude_term(world["term"]["id"], registrar_headers)
    validate_success(res, 200)

    er_final = get_enrollment_request(er["id"])
    assert er_final["academic_status"] == "REJECTED"
