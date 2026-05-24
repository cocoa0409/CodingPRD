"""RBAC / role isolation tests.

Covers Corner-design Section 7 (rbac) — peer-role isolation across
AdmissionsOfficer, Recommender, Applicant, FinancialAidOfficer, and
Anonymous.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, build_user_headers,
    setup_clock_and_school, register_applicant, create_application,
    setup_under_review_application,
    create_application_payload, decide_payload,
    make_applicant_headers, make_recommender_headers,
    admissions_headers, fa_officer_headers,
    create_recommender_invited,
)


# ─── rbac_admissions_officer_cannot_create_application ──────────────────

def test_admissions_officer_cannot_create_application(api):
    """PRD §2.1: "When the role is recognized but is not permitted to
    invoke the requested endpoint per the per-endpoint authorization
    table in §4, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP
    403)."
    PRD §4: the per-endpoint table lists "POST /applications | Create a
    draft Application | Applicant".

    Design: Corner/rbac/rbac_admissions_officer_cannot_create_application
    """
    school = setup_clock_and_school(name="RB-1")
    applicant = register_applicant(email="rb@example.com")
    res = api.create_application(
        create_application_payload(applicant["id"], school["id"], "REGULAR"),
        admissions_headers())
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── rbac_recommender_cannot_submit_application ─────────────────────────

def test_recommender_cannot_submit_application(api):
    """PRD §4: "POST /applications/{id}/submit | Applicant submits a
    DRAFT application | Applicant" — Recommender is not listed.

    Design: Corner/rbac/rbac_recommender_cannot_submit_application
    """
    school = setup_clock_and_school(name="RB-2")
    applicant = register_applicant(email="rb2@example.com")
    rec = create_recommender_invited(applicant["id"])
    app = create_application(applicant["id"], school["id"], "REGULAR")

    res = api.submit_application(
        app["id"], make_recommender_headers(rec["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── rbac_applicant_cannot_create_school ────────────────────────────────

def test_applicant_cannot_create_school(api):
    """PRD §4: "POST /schools | Create a School and its companion
    AdmissionCycle | PlatformAdmin" — Applicant is not listed.

    Design: Corner/rbac/rbac_applicant_cannot_create_school
    """
    applicant = register_applicant(email="rb3@example.com")
    res = api.create_school(
        {"name": "RB-3", "target_class_size": 5,
         "ed_deadline_iso": "2030-11-01T00:00:00Z",
         "ea_deadline_iso": "2030-11-15T00:00:00Z",
         "rd_deadline_iso": "2031-01-01T00:00:00Z",
         "rolling_open": False, "requires_css_profile": False,
         "cooldown_ms": 86_400_000},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── rbac_financial_aid_officer_cannot_decide_application ───────────────

def test_financial_aid_officer_cannot_decide_application(api):
    """PRD §4: "POST /applications/{id}/decide | Admissions renders a
    decision (ADMIT, WAITLIST, DENY, or DEFER) | AdmissionsOfficer" —
    FinancialAidOfficer is not listed.

    Design: Corner/rbac/rbac_financial_aid_officer_cannot_decide_application
    """
    _, _, _, reviewed = setup_under_review_application(plan="REGULAR")
    res = api.decide_application(
        reviewed["id"],
        decide_payload("ADMIT", reviewed["version"]),
        fa_officer_headers())
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── rbac_anonymous_only_on_declared_endpoints ──────────────────────────

def test_anonymous_get_school_returns_missing_auth_headers(api):
    """PRD §2.1: "Every request — except the three explicitly public
    endpoints (applicant self-registration, recommender acceptance of an
    invitation, and recommender decline of an invitation) — must carry
    two HTTP headers: X-User-ID, which identifies the acting principal,
    and X-User-Role, which selects that principal's operational
    capacity."
    PRD §2.1: "When either header is missing on a non-public endpoint,
    the request is rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

    Design: Corner/rbac/rbac_anonymous_only_on_declared_endpoints
    """
    school = setup_clock_and_school(name="RB-5")
    res = api.get_school(school["id"], headers={})
    validate_error(res, "ERR_MISSING_AUTH_HEADERS")
