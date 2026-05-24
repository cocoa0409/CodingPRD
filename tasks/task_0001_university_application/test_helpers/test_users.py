"""Pre-built role headers.

Per PRD §2.1, two roles bind to persisted entities (entity_backed):
  - Applicant — X-User-ID is the Applicant.id; ownership-gated calls
    MUST use make_applicant_headers(applicant_id).
  - Recommender — X-User-ID is the Recommender.id; ownership-gated calls
    MUST use make_recommender_headers(recommender_id).

The other three roles are opaque (AdmissionsOfficer, FinancialAidOfficer,
PlatformAdmin) — a shared constant suffices because the server does not
compare X-User-ID against any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — canonical shared form.
    "admissions_officer_headers": build_user_headers(
        "test-admissions-officer-1", "AdmissionsOfficer"),
    "financial_aid_officer_headers": build_user_headers(
        "test-fa-officer-1", "FinancialAidOfficer"),
    "platform_admin_headers": build_user_headers(
        "test-platform-admin-1", "PlatformAdmin"),

    # Entity-backed roles — fallback constants for non-ownership tests
    # (e.g., ERR_FORBIDDEN_ROLE checks that don't actually touch an owned
    # resource). Fixtures that create real Applicants or Recommenders
    # MUST use the make_*_headers() builders below instead.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "recommender_headers": build_user_headers("test-recommender-1", "Recommender"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """Build Applicant headers bound to a specific Applicant.id.

    Use this whenever the call exercises ownership of an Applicant-owned
    resource (Application, EssaySubmission, RecommendationLetter request,
    FinancialAidProfile).
    """
    return build_user_headers(applicant_id, "Applicant")


def make_recommender_headers(recommender_id: str) -> dict:
    """Build Recommender headers bound to a specific Recommender.id.

    Use this whenever the call exercises ownership of a RecommendationLetter
    (start/submit).
    """
    return build_user_headers(recommender_id, "Recommender")


def admissions_headers() -> dict:
    return TEST_USERS["admissions_officer_headers"]


def fa_officer_headers() -> dict:
    return TEST_USERS["financial_aid_officer_headers"]


def admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]
