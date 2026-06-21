"""Validation precedence among domain rules and the student-HOLD safety gate."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    make_officer_headers, make_student_headers,
    create_student, create_building, create_room, create_cycle,
    create_draft_application, create_submitted_application,
    run_lottery, open_assignment,
)

OFFICER = make_officer_headers()


# ─── Difficulty: state precedence over hold (priority pair) ───────────────────

def test_accept_declined_app_with_held_student_returns_invalid_state(api):
    """PRD §2.8: "Only after these gates do domain rules apply — date-range
    validity, state validity, cross-entity preconditions, gender compatibility,
    hold status, overlap and capacity ceilings, group sizing, settlement,
    duplicate prevention, and finally the optimistic-concurrency version check."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_accept_declined_app_and_hold
    """
    # An application that is already DECLINED whose student is also on HOLD.
    # Accepting violates both state validity (wrong source status) and hold
    # status; state validity precedes hold status, so ERR_INVALID_STATE wins.
    student = create_student(full_name="Dual Fail D", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=70)
    building = create_building(name="Conflict Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="CF1", room_type="SINGLE")
    cycle = create_cycle(term_label="FALL_2026I")
    app = create_submitted_application(cycle["id"], student["id"],
                                       preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    # Capture a version before mutating, then decline + place hold.
    current = validate_success(api.get_application(app["id"], OFFICER), 200)
    app_v = current["version"]
    validate_success(api.decline_application(app["id"], make_student_headers(student["id"])), 200)
    validate_success(api.place_hold_student(student["id"], OFFICER), 200)
    res = api.accept_application(
        app["id"], {"expected_application_version": app_v},
        make_student_headers(student["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_accept_declined_app_with_held_student_stays_declined(api):
    """PRD §3.6: "A student may instead decline an offer during the assignment
    window, moving the application from `OFFERED` to the terminal `DECLINED` (a
    non-`ASSIGNMENT_OPEN` phase fails with `ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_accept_declined_app_and_hold
    """
    student = create_student(full_name="Dual Fail E", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=71)
    building = create_building(name="Conflict2 Hall", building_type="TRADITIONAL")
    create_room(building["id"], room_number="CF2", room_type="SINGLE")
    cycle = create_cycle(term_label="FALL_CONF2")
    app = create_submitted_application(cycle["id"], student["id"],
                                       preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    current = validate_success(api.get_application(app["id"], OFFICER), 200)
    app_v = current["version"]
    validate_success(api.decline_application(app["id"], make_student_headers(student["id"])), 200)
    validate_success(api.place_hold_student(student["id"], OFFICER), 200)
    api.accept_application(app["id"], {"expected_application_version": app_v},
                          make_student_headers(student["id"]))
    after = validate_success(api.get_application(app["id"], OFFICER), 200)
    assert after["status"] == "DECLINED"


# ─── Corner: submit while on HOLD (isolated single-failure scenario) ──────────

def test_submit_while_student_on_hold_rejected(api):
    """PRD §3.3: "The applicant's student must be `ACTIVE` — a student on `HOLD`
    is rejected with `ERR_STUDENT_ON_HOLD` (HTTP 409)."

    Design: Corner/validations/submit_while_student_on_hold_rejected
    """
    student = create_student(full_name="Hold H", class_year="SENIOR",
                             gender_identity="MALE", lottery_number=380)
    cycle = create_cycle(term_label="HOLD_T")
    app = create_draft_application(cycle["id"], student["id"], preferred_room_type="SINGLE")
    validate_success(api.place_hold_student(student["id"], OFFICER), 200)
    res = api.submit_application(app["id"], make_student_headers(student["id"]))
    validate_error(res, "ERR_STUDENT_ON_HOLD")
    after = validate_success(api.get_application(app["id"], OFFICER), 200)
    assert after["status"] == "DRAFT"
