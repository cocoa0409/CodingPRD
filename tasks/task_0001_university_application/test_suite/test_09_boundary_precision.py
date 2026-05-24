"""Boundary precision tests.

Covers difficulty Rule 6 (boundary_precision_check) — essay word_count
inclusive boundary and Recommender IN_PROGRESS capacity boundary; and
Rule 8 (resource_temporal_overlap) — school deadline ordering and yield
cooldown closed lower bound.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_clock_and_school, register_applicant, create_application,
    create_essay, invite_and_accept_recommender,
    create_recommender_invited, create_and_submit_letter,
    create_requested_letter,
    submit_application, start_review, decide, advance_clock_to,
    create_school_payload,
    make_applicant_headers, make_recommender_headers, admissions_headers,
    admin_headers, api_client,
    make_body_with_word_count,
    ESSAY_WORD_COUNT_MAX, RECOMMENDER_INPROGRESS_CAP,
)


# ============================================================================
# Difficulty Rule 6 — Boundary precision
# ============================================================================

def test_essay_word_count_651_rejected_650_accepted(api):
    """PRD §3.5: "word_count must fall in the range from 1 through 650
    words inclusive; a word_count outside that range is rejected with
    ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE."

    Design: Difficulty/boundary_precision_check/essay_word_count_upper_boundary_inclusive
    """
    school = setup_clock_and_school(name="ESS-WC")
    applicant = register_applicant(email="ess@example.com")
    invite_and_accept_recommender(applicant["id"])
    app_651 = create_application(applicant["id"], school["id"], "REGULAR")

    # 651 tokens → rejected.
    body_651 = make_body_with_word_count(651)
    res_651 = api.create_essay(
        {"application_id": app_651["id"], "prompt_code": "PROMPT",
         "body": body_651},
        make_applicant_headers(applicant["id"]))
    validate_error(res_651, "ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE")

    # On a fresh DRAFT application, 650 tokens → accepted (inclusive).
    from test_helpers import create_school
    other_school = create_school(name="ESS-WC-650")
    app_650 = create_application(applicant["id"], other_school["id"], "REGULAR")
    body_650 = make_body_with_word_count(650)
    res_650 = api.create_essay(
        {"application_id": app_650["id"], "prompt_code": "PROMPT",
         "body": body_650},
        make_applicant_headers(applicant["id"]))
    essay = validate_success(res_650, 201)
    assert essay["word_count"] == 650


def test_recommender_inprogress_capacity_sixth_rejected(api):
    """PRD §3.2: "the count of RecommendationLetter rows pointing at this
    recommender whose status is IN_PROGRESS must remain at or below five
    after the transition. Five active drafts is permitted; a sixth
    REQUESTED → IN_PROGRESS transition is rejected with
    ERR_RECOMMENDER_OVER_CAPACITY."

    Design: Difficulty/boundary_precision_check/recommender_inprogress_capacity_boundary_inclusive
    """
    setup_clock_and_school()
    from test_helpers import create_school
    schools = [create_school(name=f"CAP-{c}") for c in "ABCDEF"]

    applicant = register_applicant(email="cap@example.com")
    rec = invite_and_accept_recommender(applicant["id"])

    apps = [create_application(applicant["id"], s["id"], "REGULAR")
            for s in schools]
    letters = [create_requested_letter(a["id"], applicant["id"], rec["id"])
               for a in apps]

    # Start the first 5 — all accepted (boundary is inclusive at 5).
    for i in range(5):
        validate_success(api.start_letter(
            letters[i]["id"], make_recommender_headers(rec["id"])), 200)

    # 6th start exceeds the cap → rejected.
    res = api.start_letter(letters[5]["id"],
                           make_recommender_headers(rec["id"]))
    validate_error(res, "ERR_RECOMMENDER_OVER_CAPACITY")


# ============================================================================
# Difficulty Rule 8 — Resource temporal overlap
# ============================================================================

def test_school_deadline_zero_width_touch_rejected(api):
    """PRD §3.3: "The intervals are half-open — each plan's submission
    window ends exclusively at its deadline — and a school whose
    Early-Decision deadline equals its Early-Action deadline at the same
    instant (a zero-width overlap) is rejected with ERR_SCHOOL_DEADLINE_ORDER."

    Design: Difficulty/resource_temporal_overlap/school_deadline_zero_width_touch_rejected_half_open
    """
    advance_clock_to("2030-10-01T00:00:00Z")
    res = api.create_school(
        {"name": "OVL-1", "target_class_size": 5,
         "ed_deadline_iso": "2030-11-01T00:00:00Z",
         "ea_deadline_iso": "2030-11-01T00:00:00Z",  # zero-width touch
         "rd_deadline_iso": "2031-01-01T00:00:00Z",
         "rolling_open": False, "requires_css_profile": False,
         "cooldown_ms": 86_400_000},
        admin_headers())
    validate_error(res, "ERR_SCHOOL_DEADLINE_ORDER")


def test_yield_cooldown_within_24h_rejected(api):
    """PRD §3.7: "the cooldown rule: the server clock must satisfy
    server-clock at or after the value of last_yield_run_at plus
    86,400,000 milliseconds (the rule's lower boundary is inclusive — a
    run at exactly twenty-four hours after the prior run is permitted).
    ... A run that violates the cooldown is rejected with
    ERR_YIELD_COOLDOWN_ACTIVE."

    Design: Difficulty/resource_temporal_overlap/yield_cooldown_closed_lower_bound_buffer
    """
    # target_class_size=1 with 2 waitlisted: the first run promotes 1 and
    # leaves 1 still WAITLISTED (open_seats=1 < waitlist length=2). That way
    # the second run still has open_seats>0 AND a WAITLISTED row, so the
    # cooldown check (priority 19) is the only remaining failure path.
    school = setup_clock_and_school(name="OVL-2", target_class_size=1)
    applicants_and_apps = []
    for i in range(2):
        a = register_applicant(email=f"yc_{i}@example.com")
        rec = invite_and_accept_recommender(a["id"])
        app = create_application(a["id"], school["id"], "REGULAR")
        create_essay(app["id"], a["id"])
        create_and_submit_letter(app["id"], a["id"], rec["id"])
        submit_application(app["id"], a["id"])
        reviewed = start_review(app["id"])
        decide(app["id"], "WAITLIST", reviewed["version"])
        applicants_and_apps.append((a, app))

    # First yield run — succeeds, sets last_yield_run_at to current clock.
    get_success_data(api.run_yield(school["id"], admissions_headers()))

    # 1 hour later — well within 24h cooldown.
    advance_clock_to("2030-10-01T01:00:00Z")

    res = api.run_yield(school["id"], admissions_headers())
    validate_error(res, "ERR_YIELD_COOLDOWN_ACTIVE")
