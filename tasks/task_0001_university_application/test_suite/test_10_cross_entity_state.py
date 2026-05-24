"""Cross-entity state-dependency tests.

Covers difficulty Rule 7 (cross_entity_state_dependency):
  - RecommendationLetter ↔ Application: letter start blocked when
    application is not DRAFT.
  - Application ↔ School: waitlist promotion blocked when school posture
    is AT_TARGET.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_clock_and_school, register_applicant,
    invite_and_accept_recommender, create_application,
    create_essay, create_and_submit_letter, create_requested_letter,
    submit_application, start_review, decide,
    make_applicant_headers, make_recommender_headers, admissions_headers,
)  # noqa: F401  — some symbols are used by sibling tests in this file


def test_letter_start_rejected_when_application_not_draft(api):
    """PRD §3.2: "this transition requires that the recommender's
    invite_status be ACCEPTED and that the owning application's status
    still be DRAFT (a letter cannot be drafted once the application is
    locked)."

    Design: Difficulty/cross_entity_state_dependency/letter_start_blocked_when_application_not_draft
    """
    school = setup_clock_and_school(name="CE1")
    applicant = register_applicant(email="ce1@example.com")
    rec_b = invite_and_accept_recommender(applicant["id"])

    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])

    # Create a REQUESTED letter pointing at rec_b.
    letter_b = create_requested_letter(app["id"], applicant["id"], rec_b["id"])

    # Move the application out of DRAFT via withdraw (PRD §4 endpoint table:
    # "withdraw — Applicant withdraws from any non-terminal state"). Withdraw
    # is the simplest transition that takes the application out of DRAFT
    # while preserving the REQUESTED letter we need for the trigger; submit
    # cannot be used here because PRD §3.4 requires all letters be SUBMITTED
    # for the DRAFT→SUBMITTED transition.
    withdrawn = validate_success(api.withdraw_application(
        app["id"], make_applicant_headers(applicant["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    # TRIGGER: try to start letter_b on the now-non-DRAFT application.
    res = api.start_letter(letter_b["id"],
                           make_recommender_headers(rec_b["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_waitlist_promotion_blocked_when_posture_at_target(api):
    """PRD §3.7: "the open-seats rule: the school's posture must be OPEN
    (that is, confirmed_enrollment_count is strictly less than
    target_class_size) AND there must be at least one application at this
    school in WAITLISTED status; a run against an AT_TARGET or
    OVER_TARGET school, or against a school with no waitlist, is rejected
    with ERR_NO_OPEN_SEATS."

    Design: Difficulty/cross_entity_state_dependency/waitlist_promotion_blocked_when_school_posture_not_open
    """
    school = setup_clock_and_school(name="CE2", target_class_size=1)
    # Applicant 1 → ADMITTED → ENROLLED → school posture = AT_TARGET.
    a1 = register_applicant(email="ce2a@example.com")
    rec1 = invite_and_accept_recommender(a1["id"])
    app1 = create_application(a1["id"], school["id"], "EARLY_DECISION")
    create_essay(app1["id"], a1["id"])
    create_and_submit_letter(app1["id"], a1["id"], rec1["id"])
    submit_application(app1["id"], a1["id"])
    reviewed1 = start_review(app1["id"])
    admitted1 = decide(app1["id"], "ADMIT", reviewed1["version"])
    get_success_data(api.accept_offer(
        admitted1["id"], make_applicant_headers(a1["id"])))

    # Applicant 2 → WAITLISTED.
    a2 = register_applicant(email="ce2b@example.com")
    rec2 = invite_and_accept_recommender(a2["id"])
    app2 = create_application(a2["id"], school["id"], "REGULAR")
    create_essay(app2["id"], a2["id"])
    create_and_submit_letter(app2["id"], a2["id"], rec2["id"])
    submit_application(app2["id"], a2["id"])
    reviewed2 = start_review(app2["id"])
    waitlisted = decide(app2["id"], "WAITLIST", reviewed2["version"])
    assert waitlisted["status"] == "WAITLISTED"

    # TRIGGER: run yield. School.posture is AT_TARGET → rejected.
    res = api.run_yield(school["id"], admissions_headers())
    validate_error(res, "ERR_NO_OPEN_SEATS")

    # The waitlisted application is unchanged.
    app2_state = validate_success(api.get_application(
        app2["id"], make_applicant_headers(a2["id"])), 200)
    assert app2_state["status"] == "WAITLISTED"
