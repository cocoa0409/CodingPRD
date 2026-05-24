"""Cascading side-effect tests.

Covers difficulty Rule 4 (transitive_cascade) — depth-3 ED accept-offer
cascade and depth-2 Recommender decline cascade.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    setup_clock_and_school, register_applicant,
    invite_and_accept_recommender, create_recommender_invited,
    create_application, create_essay, create_and_submit_letter,
    create_requested_letter,
    submit_application, start_review, decide,
    make_applicant_headers, admissions_headers, admin_headers,
)


# ─── Difficulty/transitive_cascade/ed_accept_offer_cascade_three_deep ───

def test_ed_accept_offer_cascades_three_levels_deep(api):
    """PRD §2.7: "If the accepted application's plan is Early Decision,
    every other application owned by the same applicant whose status is
    DRAFT, SUBMITTED, UNDER_REVIEW, ADMITTED, WAITLISTED, or DEFERRED
    auto-transitions to WITHDRAWN (a second-order cascade — the
    binding-ED commitment retires every other open candidacy). For each
    such cascaded withdrawal whose prior status was WAITLISTED, the freed
    school's remaining waitlisted applications have their waitlist_rank
    recomputed in the same call (a third-order cascade — the queue
    closes up behind the departing applicant)."

    Design: Difficulty/transitive_cascade/ed_accept_offer_cascade_three_deep
    """
    setup_clock_and_school()
    from test_helpers import create_school
    s1 = create_school(name="Cascade-S1", target_class_size=10)
    s2 = create_school(name="Cascade-S2", target_class_size=10)
    s3 = create_school(name="Cascade-S3", target_class_size=10)

    a = register_applicant(email="cas_a@example.com", gpa=3.9, sat_total=1550)
    rec_a = invite_and_accept_recommender(a["id"])
    b = register_applicant(email="cas_b@example.com", gpa=3.7, sat_total=1400)
    rec_b = invite_and_accept_recommender(b["id"])

    # App1: ED on S1 → ADMITTED
    app1 = create_application(a["id"], s1["id"], "EARLY_DECISION")
    create_essay(app1["id"], a["id"])
    create_and_submit_letter(app1["id"], a["id"], rec_a["id"])
    submit_application(app1["id"], a["id"])
    reviewed1 = start_review(app1["id"])
    admitted1 = decide(app1["id"], "ADMIT", reviewed1["version"])

    # App2: REGULAR on S2 → WAITLISTED
    app2 = create_application(a["id"], s2["id"], "REGULAR")
    create_essay(app2["id"], a["id"])
    create_and_submit_letter(app2["id"], a["id"], rec_a["id"])
    submit_application(app2["id"], a["id"])
    reviewed2 = start_review(app2["id"])
    decide(app2["id"], "WAITLIST", reviewed2["version"])

    # Another applicant on S2 also WAITLISTED so depth-3 rank recompute
    # has something to observe.
    appB = create_application(b["id"], s2["id"], "REGULAR")
    create_essay(appB["id"], b["id"])
    create_and_submit_letter(appB["id"], b["id"], rec_b["id"])
    submit_application(appB["id"], b["id"])
    reviewed_b = start_review(appB["id"])
    decided_b = decide(appB["id"], "WAITLIST", reviewed_b["version"])
    assert decided_b["waitlist_rank"] == 2  # behind app2

    # App3: REGULAR on S3 in SUBMITTED (non-terminal)
    app3 = create_application(a["id"], s3["id"], "REGULAR")
    create_essay(app3["id"], a["id"])
    create_and_submit_letter(app3["id"], a["id"], rec_a["id"])
    submit_application(app3["id"], a["id"])

    # TRIGGER: accept the ED offer.
    get_success_data(api.accept_offer(app1["id"], make_applicant_headers(a["id"])))

    # Depth 1: app1 → ENROLLED; S1.confirmed_enrollment_count → 1
    a1_state = validate_success(api.get_application(
        app1["id"], make_applicant_headers(a["id"])), 200)
    assert a1_state["status"] == "ENROLLED"
    s1_state = validate_success(api.get_school(s1["id"], admin_headers()), 200)
    assert s1_state["confirmed_enrollment_count"] == 1

    # Depth 2: app2 and app3 → WITHDRAWN.
    app2_state = validate_success(api.get_application(
        app2["id"], make_applicant_headers(a["id"])), 200)
    assert app2_state["status"] == "WITHDRAWN"
    app3_state = validate_success(api.get_application(
        app3["id"], make_applicant_headers(a["id"])), 200)
    assert app3_state["status"] == "WITHDRAWN"

    # Depth 3: appB.waitlist_rank recomputed from 2 → 1.
    appB_state = validate_success(api.get_application(
        appB["id"], make_applicant_headers(b["id"])), 200)
    assert appB_state["waitlist_rank"] == 1


# ─── Difficulty/transitive_cascade/recommender_decline_two_step_cascade ─

def test_recommender_decline_two_step_cascade_to_profile_status(api):
    """PRD §2.7: "When a recommender declines an invitation, every
    RecommendationLetter row pointing at that recommender whose status is
    REQUESTED is deleted as a first-order cascade. For each owning
    application, if the deletion removes the last Recommender row
    associated with that applicant and the applicant's profile_status was
    READY, the profile is re-evaluated and may flip back to DRAFT as a
    second-order cascade"

    Design: Difficulty/transitive_cascade/recommender_decline_two_step_cascade
    """
    school = setup_clock_and_school(name="Decline-S")
    applicant = register_applicant(email="dec@example.com",
                                   full_name="Dec User", gpa=3.5, sat_total=1200)
    # Invite a single recommender — profile flips to READY when the
    # row exists (PRD §3.1).
    rec = create_recommender_invited(applicant["id"])

    before = validate_success(api.get_applicant(
        applicant["id"], make_applicant_headers(applicant["id"])), 200)
    assert before["profile_status"] == "READY", \
        "PRD §3.1: profile_status flips to READY when a Recommender row exists"

    app = create_application(applicant["id"], school["id"], "REGULAR")
    letter = create_requested_letter(app["id"], applicant["id"], rec["id"])

    # TRIGGER: recommender declines.
    get_success_data(api.decline_recommender(rec["id"]))

    # Depth 2: applicant.profile_status flips back to DRAFT — no remaining
    # Recommender rows.
    after = validate_success(api.get_applicant(
        applicant["id"], make_applicant_headers(applicant["id"])), 200)
    assert after["profile_status"] == "DRAFT"
