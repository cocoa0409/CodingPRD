"""Validation tests covering Section 4 of the Corner-design index plus
difficulty Rule 5 (priority pair conflicts).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_clock_and_school, register_applicant, create_application,
    create_essay, invite_and_accept_recommender, create_requested_letter,
    create_and_submit_letter, setup_under_review_application,
    setup_admitted_application, setup_admitted_with_fa_profile,
    submit_application, start_review, decide,
    create_aid_offer_payload, decide_payload,
    advance_clock_to,
    make_applicant_headers, admissions_headers, fa_officer_headers,
    api_client,
)


# ============================================================================
# Difficulty Rule 5 — Priority-pair validation conflicts
# ============================================================================

def test_ed_submit_deadline_passed_wins_over_missing_letter(api):
    """PRD §2.6: "When a single request would trip more than one validation,
    the server returns the rejection from the lowest-numbered priority in
    this ordering — the priority decides which error the client sees first,
    irrespective of the order in which the checks happen to be coded."
    PRD §2.6: "plan-deadline window (priority 12, ERR_DEADLINE_PASSED); ...
    Early-Decision letter requirement (priority 15, ERR_ED_REQUIRES_LETTER)"

    Design: Difficulty/priority_pair_validation_conflict/ed_submit_deadline_passed_beats_missing_letter
    """
    school = setup_clock_and_school(
        clock_iso="2030-10-15T00:00:00Z",
        name="P5A",
        ed_deadline_iso="2030-11-01T00:00:00Z",
    )
    applicant = register_applicant(email="p5a@example.com", gpa=3.7, sat_total=1400)
    # Invite but do NOT accept — profile_status flips to READY because the
    # PRD §3.1 invariant is "full_name and gpa present AND >=1 Recommender
    # row exists" (no acceptance required for the row to count).
    from test_helpers import create_recommender_invited
    create_recommender_invited(applicant["id"])
    app = create_application(applicant["id"], school["id"], "EARLY_DECISION")
    create_essay(app["id"], applicant["id"])  # essay present so word_count not the failure
    advance_clock_to("2030-12-01T00:00:00Z")  # past ED deadline

    res = api.submit_application(app["id"],
                                 make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_DEADLINE_PASSED")


def test_yield_run_no_open_seats_wins_over_cooldown_active(api):
    """PRD §2.6: "open-seats precondition for yield runs (priority 18,
    ERR_NO_OPEN_SEATS); yield-run cooldown (priority 19,
    ERR_YIELD_COOLDOWN_ACTIVE)"
    PRD §3.7: "a run against an AT_TARGET or OVER_TARGET school, or
    against a school with no waitlist, is rejected with
    ERR_NO_OPEN_SEATS."

    Design: Difficulty/priority_pair_validation_conflict/yield_run_no_open_seats_beats_cooldown_active
    """
    school = setup_clock_and_school(name="P5B", target_class_size=1)
    # Applicant 1 → WAITLISTED
    a1 = register_applicant(email="p5b1@example.com")
    rec1 = invite_and_accept_recommender(a1["id"])
    app1 = create_application(a1["id"], school["id"], "REGULAR")
    create_essay(app1["id"], a1["id"])
    create_and_submit_letter(app1["id"], a1["id"], rec1["id"])
    submit_application(app1["id"], a1["id"])
    reviewed1 = start_review(app1["id"])
    decide(app1["id"], "WAITLIST", reviewed1["version"])

    # Applicant 2 → WAITLISTED so a waitlist still exists after the first yield.
    a2 = register_applicant(email="p5b2@example.com")
    rec2 = invite_and_accept_recommender(a2["id"])
    app2 = create_application(a2["id"], school["id"], "REGULAR")
    create_essay(app2["id"], a2["id"])
    create_and_submit_letter(app2["id"], a2["id"], rec2["id"])
    submit_application(app2["id"], a2["id"])
    reviewed2 = start_review(app2["id"])
    decide(app2["id"], "WAITLIST", reviewed2["version"])

    # Successful yield run — promotes Applicant 1.
    get_success_data(api.run_yield(school["id"], admissions_headers()))
    # Applicant 1 accepts → confirmed_enrollment_count=1, posture=AT_TARGET.
    get_success_data(api.accept_offer(
        app1["id"], make_applicant_headers(a1["id"])))

    # Only 1 hour later — within cooldown AND posture != OPEN.
    advance_clock_to("2030-10-01T01:00:00Z")

    res = api.run_yield(school["id"], admissions_headers())
    # Priority 18 (no_open_seats) < priority 19 (cooldown) → fiscal wins.
    validate_error(res, "ERR_NO_OPEN_SEATS")


# ============================================================================
# Corner Section 4 — Validations
# ============================================================================

# ─── validation_priority_4_path_not_found_before_body_fk ────────────────

def test_path_not_found_returns_resource_not_found(api):
    """PRD §2.5: "the server validates each identifier in left-to-right
    order. The first identifier that does not resolve to an existing row
    produces an immediate ERR_RESOURCE_NOT_FOUND (HTTP 404); the server
    does not continue validating downstream segments."

    Design: Corner/validations/validation_priority_4_path_not_found_before_body_fk
    """
    applicant = register_applicant()
    res = api.submit_application(
        "00000000-0000-4000-8000-000000000099",
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ─── validation_priority_1_missing_auth_headers ─────────────────────────

def test_missing_auth_headers_returns_err_missing_auth_headers(api):
    """PRD §2.1: "When either header is missing on a non-public endpoint,
    the request is rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

    Design: Corner/validations/validation_priority_1_missing_auth_headers
    """
    school = setup_clock_and_school(name="NH-1")
    res = api.get_school(school["id"], headers={})
    validate_error(res, "ERR_MISSING_AUTH_HEADERS")


# ─── validation_priority_2_unknown_role ─────────────────────────────────

def test_unknown_role_returns_err_unknown_role(api):
    """PRD §2.1: "When X-User-Role is present but is not one of the five
    recognized values, the request is rejected with ERR_UNKNOWN_ROLE
    (HTTP 401)."

    Design: Corner/validations/validation_priority_2_unknown_role
    """
    res = api.list_schools(headers={"X-User-Role": "Wizard",
                                    "X-User-ID": "some-id"})
    validate_error(res, "ERR_UNKNOWN_ROLE")


# ─── validation_priority_6_not_resource_owner ───────────────────────────

def test_non_owner_withdraw_returns_err_not_resource_owner(api):
    """PRD §2.1: "When a request is correctly authenticated but the actor
    does not own the targeted resource (for example, an applicant trying
    to submit another applicant's application), the rejection is
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/validations/validation_priority_6_not_resource_owner
    """
    school = setup_clock_and_school(name="OWN-1")
    owner = register_applicant(email="ownA@example.com")
    actor = register_applicant(email="ownB@example.com")
    app = create_application(owner["id"], school["id"], "REGULAR")

    res = api.withdraw_application(
        app["id"], make_applicant_headers(actor["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─── validation_priority_11_ed_binding_violation ────────────────────────

def test_second_ed_application_returns_ed_binding_violation(api):
    """PRD §3.4: "The Early-Decision binding rule applies at creation and
    again at submission: an applicant may have at most one application
    with plan equal to EARLY_DECISION in any non-terminal status. A second
    Early-Decision application is rejected with ERR_ED_BINDING_VIOLATION."

    Design: Corner/validations/validation_priority_11_ed_binding_violation
    """
    setup_clock_and_school()  # advance clock; we'll create two schools.
    from test_helpers import create_school
    s1 = create_school(name="ED-1")
    s2 = create_school(name="ED-2")
    applicant = register_applicant(email="ed@example.com")

    validate_success(api.create_application(
        {"applicant_id": applicant["id"], "school_id": s1["id"],
         "plan": "EARLY_DECISION"},
        make_applicant_headers(applicant["id"])), 201)
    res = api.create_application(
        {"applicant_id": applicant["id"], "school_id": s2["id"],
         "plan": "EARLY_DECISION"},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ED_BINDING_VIOLATION")


# ─── validation_priority_13_already_enrolled ────────────────────────────

def test_accept_offer_when_already_enrolled_returns_already_enrolled(api):
    """PRD §3.4: "no other application by this applicant is in ENROLLED
    status — the single-enrollment rule, rejected with ERR_ALREADY_ENROLLED
    on violation."

    Design: Corner/validations/validation_priority_13_already_enrolled
    """
    school1 = setup_clock_and_school(name="AE-1", target_class_size=10)
    from test_helpers import create_school
    school2 = create_school(name="AE-2", target_class_size=10)

    applicant = register_applicant(email="ae@example.com")
    rec = invite_and_accept_recommender(applicant["id"])

    def _drive_to_admitted(school):
        app = create_application(applicant["id"], school["id"], "REGULAR")
        create_essay(app["id"], applicant["id"])
        create_and_submit_letter(app["id"], applicant["id"], rec["id"])
        submit_application(app["id"], applicant["id"])
        reviewed = start_review(app["id"])
        return decide(app["id"], "ADMIT", reviewed["version"])

    admitted1 = _drive_to_admitted(school1)
    admitted2 = _drive_to_admitted(school2)

    validate_success(api.accept_offer(
        admitted1["id"], make_applicant_headers(applicant["id"])), 200)
    res = api.accept_offer(
        admitted2["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ALREADY_ENROLLED")


# ─── validation_priority_17_grant_exceeds_need ──────────────────────────

def test_aid_offer_grant_exceeds_demonstrated_need_rejected(api):
    """PRD §3.6: "the grant_cents is additionally capped at the computed
    demonstrated_need_cents (see below), so a request whose grant exceeds
    demonstrated need is rejected with ERR_GRANT_EXCEEDS_NEED."

    Design: Corner/validations/validation_priority_17_grant_exceeds_need
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=2_000_000,
        family_income_cents=6_000_000,
        school_overrides={"name": "GE-1", "requires_css_profile": False},
    )
    # COA 7M, EFC 2M → demonstrated_need = 5M. Request grant = 6M (exceeds).
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=admitted["version"],
            cost_of_attendance_cents=7_000_000,
            variant="FEDERAL",
            grant_cents=6_000_000,
            loan_cents=0, work_study_cents=0),
        fa_officer_headers())
    validate_error(res, "ERR_GRANT_EXCEEDS_NEED")


# ─── validation_priority_15_ed_requires_letter ──────────────────────────

def test_submit_ed_application_without_letter_returns_ed_requires_letter(api):
    """PRD §3.4: "All RecommendationLetter rows for this application must
    be in SUBMITTED status — though zero letters is permitted, except
    when the plan is EARLY_DECISION, in which case at least one SUBMITTED
    letter is required and the missing-letter case rejects with
    ERR_ED_REQUIRES_LETTER."

    Design: Corner/validations/validation_priority_15_ed_requires_letter
    """
    school = setup_clock_and_school(
        clock_iso="2030-10-15T00:00:00Z", name="ED-NL")
    applicant = register_applicant(email="ednl@example.com", gpa=3.5)
    rec = invite_and_accept_recommender(applicant["id"])
    app = create_application(applicant["id"], school["id"], "EARLY_DECISION")
    create_essay(app["id"], applicant["id"])
    # Create letter and leave it in REQUESTED (not SUBMITTED) — submit
    # should fail with ERR_ED_REQUIRES_LETTER.
    create_requested_letter(app["id"], applicant["id"], rec["id"])

    res = api.submit_application(
        app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_ED_REQUIRES_LETTER")
