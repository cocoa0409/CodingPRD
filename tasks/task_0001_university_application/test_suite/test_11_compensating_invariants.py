"""Compensating-action invariant tests.

Covers difficulty Rule 9 (compensating_invariant):
  - School.confirmed_enrollment_count restored after accept/revoke.
  - Waitlist rank sequence restored after a waitlisted withdraw.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    setup_clock_and_school, register_applicant,
    invite_and_accept_recommender,
    create_application, create_essay, create_and_submit_letter,
    submit_application, start_review, decide, advance_clock_to,
    make_applicant_headers, admissions_headers, admin_headers,
)


# ─── Difficulty/compensating_invariant/enrollment_ledger ────────────────

def test_enrollment_count_restored_after_accept_then_revoke(api):
    """PRD §2.7: "Revoking an enrollment back to DECLINED_OFFER is the
    compensating action for accept-offer: the school's
    confirmed_enrollment_count is decremented by one and posture is
    recomputed so the invariant "confirmed_enrollment_count equals the
    count of applications at this school whose status is ENROLLED" is
    restored."

    Design: Difficulty/compensating_invariant/enrollment_ledger_invariant_under_accept_then_revoke
    """
    school = setup_clock_and_school(name="INV-1", target_class_size=5)
    applicant = register_applicant(email="inv1@example.com")
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")
    create_essay(app["id"], applicant["id"])
    create_and_submit_letter(app["id"], applicant["id"], rec["id"])
    submit_application(app["id"], applicant["id"])
    reviewed = start_review(app["id"])
    decide(app["id"], "ADMIT", reviewed["version"])

    # Before accept: posture OPEN, count 0.
    s0 = validate_success(api.get_school(school["id"], admin_headers()), 200)
    assert s0["confirmed_enrollment_count"] == 0
    assert s0["posture"] == "OPEN"

    # Accept offer → ENROLLED; count=1.
    get_success_data(api.accept_offer(
        app["id"], make_applicant_headers(applicant["id"])))
    s1 = validate_success(api.get_school(school["id"], admin_headers()), 200)
    assert s1["confirmed_enrollment_count"] == 1
    assert s1["posture"] == "OPEN"  # still <5

    # Revoke enrollment → DECLINED_OFFER; count back to 0 (invariant restored).
    get_success_data(api.revoke_enrollment(
        app["id"], make_applicant_headers(applicant["id"])))
    s2 = validate_success(api.get_school(school["id"], admin_headers()), 200)
    assert s2["confirmed_enrollment_count"] == 0
    assert s2["posture"] == "OPEN"

    revoked = validate_success(api.get_application(
        app["id"], make_applicant_headers(applicant["id"])), 200)
    assert revoked["status"] == "DECLINED_OFFER"


# ─── Difficulty/compensating_invariant/waitlist_rank_sequence ───────────

def test_waitlist_ranks_contiguous_after_middle_withdraws(api):
    """PRD §2.7: "Ranking is one-based and ordered by waitlist_added_at
    ascending, with created_at ascending as the deterministic tie-breaker;
    the id field is never used as a sort key."
    PRD §3.7: "When admissions waitlists an application, the platform
    stamps waitlist_added_at with the server clock and recomputes
    waitlist_rank across the school's full set of waitlisted applications
    ... The same recompute runs when a waitlisted application withdraws"

    Design: Difficulty/compensating_invariant/waitlist_rank_sequence_invariant_under_waitlist_then_withdraw
    """
    school = setup_clock_and_school(name="INV-2", target_class_size=10)

    def _waitlist(email_seed, clock_stamp):
        a = register_applicant(email=f"{email_seed}@example.com")
        rec = invite_and_accept_recommender(a["id"])
        app = create_application(a["id"], school["id"], "REGULAR")
        create_essay(app["id"], a["id"])
        create_and_submit_letter(app["id"], a["id"], rec["id"])
        submit_application(app["id"], a["id"])
        reviewed = start_review(app["id"])
        advance_clock_to(clock_stamp)
        return a, decide(app["id"], "WAITLIST", reviewed["version"])

    a1, app_a = _waitlist("wa", "2030-10-01T00:01:00Z")
    a2, app_b = _waitlist("wb", "2030-10-01T00:02:00Z")
    a3, app_c = _waitlist("wc", "2030-10-01T00:03:00Z")
    assert app_a["waitlist_rank"] == 1
    assert app_b["waitlist_rank"] == 2
    assert app_c["waitlist_rank"] == 3

    # Middle applicant (B) withdraws.
    get_success_data(api.withdraw_application(
        app_b["id"], make_applicant_headers(a2["id"])))

    # Remaining ranks must be contiguous 1..2 (no gap).
    a_now = validate_success(api.get_application(
        app_a["id"], make_applicant_headers(a1["id"])), 200)
    c_now = validate_success(api.get_application(
        app_c["id"], make_applicant_headers(a3["id"])), 200)
    assert a_now["waitlist_rank"] == 1
    assert c_now["waitlist_rank"] == 2

    b_now = validate_success(api.get_application(
        app_b["id"], make_applicant_headers(a2["id"])), 200)
    assert b_now["status"] == "WITHDRAWN"
    assert b_now["waitlist_rank"] is None
