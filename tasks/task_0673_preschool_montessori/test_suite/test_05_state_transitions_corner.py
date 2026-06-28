"""State-machine corner cases: invalid transitions, initial/terminal states, preconditions,
side effects, and the empty-waitlist conditional cascade
(corner-design section: state_machines). PRD §3.2, §3.5, §3.12.

Each test translates exactly one corner-design instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_classroom_payload, create_application_payload,
    set_clock, create_tier, create_classroom, create_room_with_staff,
    create_student, enroll_child, application_under_review,
    setup_enrolled_child, open_slot, book_slot,
    make_parent_headers, make_guide_headers, TEST_USERS, api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_start_review_twice_invalid_state(api):
    """PRD §3.2: "Any transition out of a state from which it is not defined — for example,
    attempting to waitlist an application that is not UNDER_REVIEW — is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/start_review_from_already_under_review_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    room = create_classroom(name="Room", level="PRIMARY", capacity=5)
    student = create_student(parent_user_id="parent-1")
    app = application_under_review(student["id"], room["id"], tier["id"],
                                   parent_user_id="parent-1")
    res = api.start_review(app["id"], REGISTRAR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_application_initial_state_submitted(api):
    """PRD §3.2: "A new application enters SUBMITTED status. Its priority_score starts at 0,
    its waitlisted_at is null until the application first reaches the waitlist".

    Design: Corner/state_machines/application_initial_state_is_submitted
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10)
    room = create_classroom(name="Room", level="PRIMARY", capacity=5)
    student = create_student(parent_user_id="parent-1")
    res = api.create_application(
        create_application_payload(student["id"], room["id"], tier["id"]),
        make_parent_headers("parent-1"))
    app = validate_success(res, 201)
    assert app["status"] == "SUBMITTED"
    assert app["version"] == 1
    assert app["priority_score"] == 0


def test_enrolled_application_rejects_decline_offer(api):
    """PRD §3.2: "Any transition out of a state from which it is not defined ... is rejected
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_enrolled_application_rejects_decline
    """
    room, tier, student, enr = setup_enrolled_child()
    app_id = enr["application_id"]
    res = api.decline_offer(app_id, make_parent_headers("parent-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_no_show_before_end_at_rejected(api):
    """PRD §3.12: "The guide may mark a booked slot as a no-show, BOOKED → NO_SHOW, but only
    once the current logical clock has reached or passed the slot's end_at."

    Design: Corner/state_machines/no_show_before_end_at_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")
    slot = open_slot(room["id"], guide_user_id="guide-1",
                     start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z")
    book_slot(slot["id"], student["id"], parent_user_id="parent-1")
    # Clock still 2026-09-01, before slot.end_at.
    res = api.no_show_slot(slot["id"], make_guide_headers("guide-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_booked_slot_clears_booked_student(api):
    """PRD §3.12: "The guide may cancel a slot that is either OPEN or BOOKED, moving it to
    CANCELLED and clearing its booked_student_id."

    Design: Corner/state_machines/cancel_slot_clears_booked_student_compensation
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")
    slot = open_slot(room["id"], guide_user_id="guide-1")
    book_slot(slot["id"], student["id"], parent_user_id="parent-1")

    res = api.cancel_slot(slot["id"], make_guide_headers("guide-1"))
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["booked_student_id"] is None, (
        f"booked_student_id must be cleared, got {cancelled['booked_student_id']}")


def test_withdraw_with_no_waitlist_leaves_seat_open(api):
    """PRD §3.5: "If no waitlisted candidate exists for the room, the promotion step simply
    does nothing and the seat stays open."

    Design: Corner/state_machines/withdraw_with_no_waitlist_leaves_seat_open
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1)
    student = create_student(parent_user_id="parent-1")
    enr = enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")

    res = api.withdraw(enr["id"], REGISTRAR)
    withdrawn = validate_success(res, 200)
    assert withdrawn["placement_status"] == "WITHDRAWN"
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_after["placed_count"] == 0
    assert room_after["compliance_status"] == "COMPLIANT"
