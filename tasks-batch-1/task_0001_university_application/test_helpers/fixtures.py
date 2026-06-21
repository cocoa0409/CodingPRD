"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading: after creating an Applicant entity, ownership-gated calls
MUST use `make_applicant_headers(applicant["id"])` — never fall back to
TEST_USERS["applicant_headers"] for ownership-gated paths.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_school_payload,
    create_application_payload,
    create_essay_payload,
    create_recommendation_request_payload,
    create_financial_aid_profile_payload,
    create_aid_package_payload,
)
from .test_users import TEST_USERS, make_applicant_headers


# ─── Tier 0: Singletons ────────────────────────────────────────────────────

def set_clock(iso8601: str) -> None:
    """Set the logical clock used for deadline checks. Anonymous per PRD §2.1.1."""
    api_client.set_clock(iso8601, TEST_USERS["platform_admin_headers"])


# ─── Tier 1: Single-entity creation ────────────────────────────────────────

def create_applicant(email: str = "applicant@u.edu", **overrides) -> dict:
    """Self-register an applicant (Anonymous endpoint)."""
    payload = create_applicant_payload(email=email, **overrides)
    return get_success_data(api_client.create_applicant(payload))


def create_school(name: str = "Test University", **overrides) -> dict:
    """PlatformAdmin creates a school."""
    payload = create_school_payload(name=name, **overrides)
    return get_success_data(
        api_client.create_school(payload, TEST_USERS["platform_admin_headers"])
    )


def create_financial_aid_profile(applicant: dict, **overrides) -> dict:
    """Create FAP for an applicant (defaults to FAFSA)."""
    payload = create_financial_aid_profile_payload(applicant["id"], **overrides)
    return get_success_data(
        api_client.create_financial_aid_profile(
            payload, make_applicant_headers(applicant["id"])
        )
    )


def create_draft_application(applicant: dict, school: dict) -> dict:
    """Applicant drafts an Application at the given school."""
    payload = create_application_payload(applicant["id"], school["id"])
    return get_success_data(
        api_client.create_application(
            payload, make_applicant_headers(applicant["id"])
        )
    )


def create_completed_essay(application: dict, applicant: dict, prompt_code: str) -> dict:
    """Create a single completed essay belonging to the application."""
    payload = create_essay_payload(application["id"], prompt_code=prompt_code)
    return get_success_data(
        api_client.create_essay(payload, make_applicant_headers(applicant["id"]))
    )


def create_submitted_recommendation(
    applicant: dict, school: dict, recommender_email: str, rating: int = 4,
) -> dict:
    """Create a recommendation invite and have PlatformAdmin submit it with rating."""
    inv_payload = create_recommendation_request_payload(
        applicant["id"], school["id"], recommender_email,
    )
    invite = get_success_data(
        api_client.create_recommendation_request(
            inv_payload, make_applicant_headers(applicant["id"])
        )
    )
    submitted = get_success_data(
        api_client.submit_recommendation_request(
            invite["id"], rating, TEST_USERS["platform_admin_headers"]
        )
    )
    return submitted


# ─── Tier 2: Multi-step compositions ──────────────────────────────────────

def setup_applicant_with_fap(
    email: str = "applicant@u.edu",
    gpa: float = 3.50,
    sat_total: int = 1300,
    residency: str = "IN_STATE",
    profile_type: str = "FAFSA",
    household_income_cents: int = 8_000_000,
    household_size: int = 4,
    declared_assets_cents: int = 0,
) -> dict:
    """Applicant + FinancialAidProfile. Returns the applicant dict."""
    # Always pass sat_total through (including explicit None for the test-optional
    # variant); factories default to 1300, which would otherwise mask a None override.
    applicant_kwargs = {"gpa_unweighted": gpa, "residency": residency, "sat_total": sat_total}
    applicant = create_applicant(email=email, **applicant_kwargs)
    fap_kwargs = {
        "household_income_cents": household_income_cents,
        "household_size": household_size,
    }
    if profile_type == "CSS_PROFILE" or declared_assets_cents > 0:
        fap_kwargs["declared_assets_cents"] = declared_assets_cents
    create_financial_aid_profile(
        applicant, profile_type=profile_type, **fap_kwargs,
    )
    return applicant


def setup_ready_to_submit_application(
    *,
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "ready",
    gpa: float = 3.50,
    sat_total: int = 1300,
    residency: str = "IN_STATE",
    num_essays: int = 2,
    num_recommendations: int = 2,
    rec_ratings=None,
    school_overrides=None,
) -> tuple:
    """Build a fully-eligible-to-submit DRAFT Application.

    Returns (applicant, school, application).
    Caller is responsible for setting the clock before submit.
    """
    if school is None:
        overrides = dict(school_overrides or {})
        school_name = overrides.pop("name", f"U {email_suffix}")
        school = create_school(name=school_name, **overrides)
    if applicant is None:
        applicant = setup_applicant_with_fap(
            email=f"{email_suffix}@u.edu",
            gpa=gpa, sat_total=sat_total, residency=residency,
        )
    application = create_draft_application(applicant, school)
    for i in range(num_essays):
        create_completed_essay(application, applicant, prompt_code=f"P{i+1}")
    if rec_ratings is None:
        rec_ratings = [4] * num_recommendations
    for i, rating in enumerate(rec_ratings):
        create_submitted_recommendation(
            applicant, school,
            recommender_email=f"r{i+1}_{email_suffix}@x.edu",
            rating=rating,
        )
    return applicant, school, application


def setup_submitted_application(
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    *,
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "sub",
    school_overrides=None,
    gpa: float = 3.50,
    sat_total: int = 1300,
    residency: str = "IN_STATE",
    num_essays: int = 2,
    rec_ratings=None,
) -> tuple:
    """Build an Application sitting in SUBMITTED. Returns (applicant, school, application)."""
    applicant, school, application = setup_ready_to_submit_application(
        school=school, applicant=applicant, email_suffix=email_suffix,
        gpa=gpa, sat_total=sat_total, residency=residency,
        num_essays=num_essays, rec_ratings=rec_ratings,
        school_overrides=school_overrides,
    )
    set_clock(submit_clock_iso)
    submitted = get_success_data(
        api_client.submit_application(
            application["id"], make_applicant_headers(applicant["id"])
        )
    )
    return applicant, school, submitted


def setup_under_review_application(
    *,
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    review_clock_iso: str = "2026-10-10T00:00:00Z",
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "ur",
    school_overrides=None,
    gpa: float = 3.50,
    sat_total: int = 1300,
    residency: str = "IN_STATE",
    rec_ratings=None,
) -> tuple:
    """Build an Application sitting in UNDER_REVIEW. Returns (applicant, school, application)."""
    applicant, school, submitted = setup_submitted_application(
        submit_clock_iso=submit_clock_iso,
        school=school, applicant=applicant, email_suffix=email_suffix,
        school_overrides=school_overrides,
        gpa=gpa, sat_total=sat_total, residency=residency,
        rec_ratings=rec_ratings,
    )
    set_clock(review_clock_iso)
    under_review = get_success_data(
        api_client.begin_review_application(
            submitted["id"], TEST_USERS["admissions_headers"]
        )
    )
    return applicant, school, under_review


def setup_admitted_application(
    *,
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    review_clock_iso: str = "2026-10-10T00:00:00Z",
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "ad",
    school_overrides=None,
    gpa: float = 3.80,
    sat_total: int = 1400,
    residency: str = "IN_STATE",
    rec_ratings=None,
) -> tuple:
    """Build an Application sitting in ADMITTED. Returns (applicant, school, application)."""
    applicant, school, under_review = setup_under_review_application(
        submit_clock_iso=submit_clock_iso,
        review_clock_iso=review_clock_iso,
        school=school, applicant=applicant, email_suffix=email_suffix,
        school_overrides=school_overrides,
        gpa=gpa, sat_total=sat_total, residency=residency,
        rec_ratings=rec_ratings,
    )
    admitted = get_success_data(
        api_client.admit_application(
            under_review["id"], under_review["version"],
            TEST_USERS["admissions_headers"],
        )
    )
    return applicant, school, admitted


def setup_aid_drafted(
    *,
    grant_cents: int = 500_000,
    loan_cents: int = 400_000,
    work_study_cents: int = 100_000,
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    review_clock_iso: str = "2026-10-10T00:00:00Z",
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "aiddraft",
    school_overrides=None,
    residency: str = "IN_STATE",
) -> tuple:
    """Admitted Application + DRAFT AidPackage. Returns (applicant, school, application, aid_package)."""
    applicant, school, admitted = setup_admitted_application(
        submit_clock_iso=submit_clock_iso, review_clock_iso=review_clock_iso,
        school=school, applicant=applicant, email_suffix=email_suffix,
        school_overrides=school_overrides, residency=residency,
    )
    aid_payload = create_aid_package_payload(
        admitted["id"], grant_cents=grant_cents, loan_cents=loan_cents,
        work_study_cents=work_study_cents,
    )
    aid_pkg = get_success_data(
        api_client.create_aid_package(aid_payload, TEST_USERS["financial_aid_headers"])
    )
    return applicant, school, admitted, aid_pkg


def setup_aid_finalized(
    *,
    grant_cents: int = 500_000,
    loan_cents: int = 400_000,
    work_study_cents: int = 100_000,
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    review_clock_iso: str = "2026-10-10T00:00:00Z",
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "aidfinal",
    school_overrides=None,
    residency: str = "IN_STATE",
) -> tuple:
    """Admitted Application + FINALIZED AidPackage. Returns (applicant, school, application, aid_package)."""
    applicant, school, admitted, aid_pkg = setup_aid_drafted(
        grant_cents=grant_cents, loan_cents=loan_cents, work_study_cents=work_study_cents,
        submit_clock_iso=submit_clock_iso, review_clock_iso=review_clock_iso,
        school=school, applicant=applicant, email_suffix=email_suffix,
        school_overrides=school_overrides, residency=residency,
    )
    finalized = get_success_data(
        api_client.finalize_aid_package(aid_pkg["id"], TEST_USERS["financial_aid_headers"])
    )
    return applicant, school, admitted, finalized


def setup_waitlisted_application(
    *,
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    review_clock_iso: str = "2026-10-10T00:00:00Z",
    school: dict = None,
    applicant: dict = None,
    email_suffix: str = "wl",
    school_overrides=None,
    gpa: float = 3.50,
    sat_total: int = 1300,
    residency: str = "IN_STATE",
    rec_ratings=None,
) -> tuple:
    """Build an Application sitting in WAITLISTED. Returns (applicant, school, application)."""
    applicant, school, under_review = setup_under_review_application(
        submit_clock_iso=submit_clock_iso, review_clock_iso=review_clock_iso,
        school=school, applicant=applicant, email_suffix=email_suffix,
        school_overrides=school_overrides,
        gpa=gpa, sat_total=sat_total, residency=residency,
        rec_ratings=rec_ratings,
    )
    waitlisted = get_success_data(
        api_client.waitlist_application(
            under_review["id"], TEST_USERS["admissions_headers"]
        )
    )
    return applicant, school, waitlisted


# ─── Tier 3: Yield-posture targeting (multi-admit loop) ────────────────────

def admit_n_applications_at_school(
    n: int,
    school: dict,
    *,
    submit_clock_iso: str = "2026-09-15T00:00:00Z",
    review_clock_iso: str = "2026-10-10T00:00:00Z",
    email_prefix: str = "yi",
) -> list:
    """Drive n full Application lifecycles to ADMITTED at the given school.

    Each iteration creates a distinct applicant + FAP + draft + essays + recs,
    submits, begins review, then admits. Returns the list of admitted applications.
    """
    admitted_apps = []
    for i in range(1, n + 1):
        suffix = f"{email_prefix}_{i}"
        _, _, admitted = setup_admitted_application(
            submit_clock_iso=submit_clock_iso, review_clock_iso=review_clock_iso,
            school=school, email_suffix=suffix,
        )
        admitted_apps.append(admitted)
    return admitted_apps
