"""Cross-entity preconditions: an application bound to a roommate group cannot
be submitted until that group is LOCKED with the submitter an ACCEPTED member."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    make_officer_headers, make_student_headers,
    create_student, create_cycle,
    create_roommate_group, invite_member, accept_member, create_draft_application,
)

OFFICER = make_officer_headers()


def test_submit_with_forming_group_rejected_precondition(api):
    """PRD §3.3: "If the application names a `roommate_group_id`, the referenced
    group must be `LOCKED` and the submitting student must be an `ACCEPTED` member
    of it; otherwise the submission is rejected with `ERR_PRECONDITION_NOT_MET`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_roommate_group_locked
    """
    owner = create_student(full_name="Group Owner", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=110)
    cycle = create_cycle(term_label="FALL_2026M")
    group = create_roommate_group(cycle["id"], owner["id"], target_size=2)
    # group is still FORMING (not LOCKED)
    app = create_draft_application(cycle["id"], owner["id"],
                                   preferred_room_type="DOUBLE",
                                   roommate_group_id=group["id"])
    res = api.submit_application(app["id"], make_student_headers(owner["id"]))
    validate_error(res, "ERR_PRECONDITION_NOT_MET")
    after = validate_success(api.get_application(app["id"], OFFICER), 200)
    assert after["status"] == "DRAFT"


def test_submit_with_locked_group_accepted_member_succeeds(api):
    """PRD §3.3: "If the application names a `roommate_group_id`, the referenced
    group must be `LOCKED` and the submitting student must be an `ACCEPTED` member
    of it; otherwise the submission is rejected with `ERR_PRECONDITION_NOT_MET`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_roommate_group_locked
    """
    owner = create_student(full_name="Locked Owner", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=111)
    mate = create_student(full_name="Locked Mate", class_year="JUNIOR",
                          gender_identity="MALE", lottery_number=112)
    cycle = create_cycle(term_label="FALL_LCK")
    group = create_roommate_group(cycle["id"], owner["id"], target_size=2)
    mem = invite_member(group["id"], owner["id"], mate["id"])
    accept_member(group["id"], mem["id"], mate["id"])  # group now full (count 2)
    locked = validate_success(api.lock_group(group["id"], make_student_headers(owner["id"])), 200)
    assert locked["status"] == "LOCKED"
    # The owner is an ACCEPTED member of the now-LOCKED group; submit succeeds.
    app = create_draft_application(cycle["id"], owner["id"],
                                   preferred_room_type="DOUBLE",
                                   roommate_group_id=group["id"])
    submitted = validate_success(
        api.submit_application(app["id"], make_student_headers(owner["id"])), 200)
    assert submitted["status"] == "SUBMITTED"
