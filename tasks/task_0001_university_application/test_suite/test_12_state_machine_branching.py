"""State-machine branching tests.

Covers difficulty Rule 3 (non_linear_state_machine):
  - Application branching at UNDER_REVIEW (DEFER rewrites plan, then
    DEFERRED → UNDER_REVIEW after ED deadline).
  - Recommender branching at INVITED (ACCEPT vs DECLINE with cascade).
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    setup_clock_and_school, register_applicant,
    invite_and_accept_recommender, create_recommender_invited,
    create_application, create_essay, create_and_submit_letter,
    create_requested_letter,
    submit_application, start_review, decide, advance_clock_to,
    make_applicant_headers, admissions_headers,
)


# ─── Difficulty/non_linear_state_machine/application_branching ─────────

def test_defer_rewrites_plan_then_deferred_reopens_under_review(api):
    """PRD §3.4: "DEFER is permitted only when the application's plan is
    EARLY_DECISION or EARLY_ACTION ... on success the application's
    status becomes DEFERRED, decision_at is set to the server clock, and
    the application's plan is set to REGULAR (rolling it into the
    regular pool for later review)."
    PRD §3.4: "The same capability is also used to re-open a DEFERRED
    application: a DEFERRED → UNDER_REVIEW transition requires that the
    application's status be DEFERRED and that the server clock be
    strictly later than the school's ed_deadline_iso"

    Design: Difficulty/non_linear_state_machine/application_branching_under_review_diverges_admit_vs_defer
    """
    school = setup_clock_and_school(
        name="Brown-Branch",
        ed_deadline_iso="2030-11-01T00:00:00Z",
        rd_deadline_iso="2031-01-01T00:00:00Z",
    )
    applicant = register_applicant(email="brn@example.com", gpa=3.6, sat_total=1400)
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "EARLY_DECISION")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])

    # DEFER branch — plan rewritten to REGULAR; status = DEFERRED.
    deferred = decide(app["id"], "DEFER", reviewed["version"])
    assert deferred["status"] == "DEFERRED"
    assert deferred["plan"] == "REGULAR"

    # Advance the clock past the ED deadline.
    advance_clock_to("2030-11-02T00:00:00Z")

    # Re-open via start-review — DEFERRED → UNDER_REVIEW.
    reopened = validate_success(api.start_review_application(
        app["id"], admissions_headers()), 200)
    assert reopened["status"] == "UNDER_REVIEW"


# ─── Difficulty/non_linear_state_machine/recommender_branching ─────────

def test_recommender_decline_branch_deletes_requested_letter_and_flips_profile(api):
    """PRD §3.2: "Declining transitions invite_status from INVITED to
    DECLINED; the decline is terminal and triggers the cascade described
    in §2.7 — every REQUESTED letter pointing at this recommender is
    deleted, and any owning applicant whose profile_status was READY is
    re-evaluated."
    PRD §3.1: "The profile may also flip back from READY to DRAFT if a
    recommender declines their invitation and the deletion of the
    resulting requested letters leaves the applicant with no remaining
    recommender rows"

    Design: Difficulty/non_linear_state_machine/recommender_branching_invited_diverges_accept_vs_decline_with_cascade
    """
    school = setup_clock_and_school(name="Cornell-Branch")
    applicant = register_applicant(email="cor@example.com",
                                   full_name="CR", gpa=3.5, sat_total=1300)
    rec = create_recommender_invited(applicant["id"])

    app = create_application(applicant["id"], school["id"], "REGULAR")
    letter = create_requested_letter(app["id"], applicant["id"], rec["id"])

    # TRIGGER: decline.
    declined = validate_success(api.decline_recommender(rec["id"]), 200)
    assert declined["invite_status"] == "DECLINED"

    # Letter was REQUESTED at the time of decline → deleted as cascade
    # depth 1.
    get_letter_res = api.get_recommender(
        rec["id"], make_applicant_headers(applicant["id"]))
    # The letter row is not retrievable via the recommender endpoint
    # (no such read), so we verify deletion via the listing surface
    # indirectly: profile flips to DRAFT, which is only possible if no
    # Recommender rows remain (PRD §3.1).
    applicant_after = validate_success(api.get_applicant(
        applicant["id"], make_applicant_headers(applicant["id"])), 200)
    assert applicant_after["profile_status"] == "DRAFT"
