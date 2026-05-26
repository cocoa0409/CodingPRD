"""Pre-built role headers for every role in the PRD.

The Applicant role's identity is `entity_backed:Applicant` — for ownership-gated
calls, fixtures MUST call `make_applicant_headers(applicant_id)` with the actual
Applicant.id rather than using the shared constant. The shared constant is a
fallback for non-ownership tests only (e.g., GET catalogue endpoints).

AdmissionsOfficer, FinancialAidOfficer, and PlatformAdmin carry `identity: opaque` —
X-User-ID is recorded but never compared to any entity id, so a shared constant
is canonical for these roles.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership-gated tests.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    # opaque roles: shared constants are canonical.
    "admissions_headers": build_user_headers("test-admissions-1", "AdmissionsOfficer"),
    "financial_aid_headers": build_user_headers("test-financial-aid-1", "FinancialAidOfficer"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Anonymous (no auth headers required, but provided for explicit anonymous calls)
    "anonymous_headers": {},
}


def make_applicant_headers(applicant_id: str) -> dict:
    """For Applicant role (entity_backed:Applicant). Pass the actual Applicant.id
    as user_id whenever the call is ownership-gated (applicant-scoped endpoints).
    """
    return build_user_headers(applicant_id, "Applicant")


def make_admissions_headers(opaque_id: str = "test-admissions-1") -> dict:
    """For AdmissionsOfficer role (identity: opaque). X-User-ID is opaque."""
    return build_user_headers(opaque_id, "AdmissionsOfficer")


def make_financial_aid_headers(opaque_id: str = "test-financial-aid-1") -> dict:
    """For FinancialAidOfficer role (identity: opaque)."""
    return build_user_headers(opaque_id, "FinancialAidOfficer")


def make_platform_admin_headers(opaque_id: str = "test-platform-admin-1") -> dict:
    """For PlatformAdmin role (identity: opaque)."""
    return build_user_headers(opaque_id, "PlatformAdmin")
