"""Pre-built role headers for every role the PRD recognises.

Four of the five roles carry an opaque identity, so a shared constant is the
canonical form for them. The `Parent` role is different: `X-User-ID` is the
`id` of the acting `ConsentRequest`, so any ownership-gated Parent call must
use `make_parent_headers(<consent_request_id>)`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles; the parent entry is only a
# fallback for calls that never reach an ownership check (for example a Parent
# hitting an endpoint its role is not authorised for at all).
TEST_USERS = {
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "engineer_headers": build_user_headers("engineer-1", "PrivacyEngineer"),
    "assessor_headers": build_user_headers("assessor-1", "SafeHarborAssessor"),
    "certifier_headers": build_user_headers("certifier-1", "SafeHarborCertifier"),
    "parent_headers": build_user_headers("00000000-0000-4000-8000-000000000420", "Parent"),
}

OFFICER_HEADERS = TEST_USERS["officer_headers"]
ENGINEER_HEADERS = TEST_USERS["engineer_headers"]
ASSESSOR_HEADERS = TEST_USERS["assessor_headers"]
CERTIFIER_HEADERS = TEST_USERS["certifier_headers"]


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """ComplianceOfficer headers. The identifier is opaque and never compared to an entity."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_engineer_headers(user_id: str = "engineer-1") -> dict:
    """PrivacyEngineer headers. The identifier is opaque and never compared to an entity."""
    return build_user_headers(user_id, "PrivacyEngineer")


def make_parent_headers(consent_request_id: str) -> dict:
    """Parent headers.

    `X-User-ID` must be the `id` of the `ConsentRequest` the parent holds; pass
    the real consent id for every ownership-gated call.
    """
    return build_user_headers(consent_request_id, "Parent")


def make_assessor_headers(user_id: str) -> dict:
    """SafeHarborAssessor headers. The identifier is stored as `preparer_user_id`."""
    return build_user_headers(user_id, "SafeHarborAssessor")


def make_certifier_headers(user_id: str) -> dict:
    """SafeHarborCertifier headers. The identifier is stored as `certifier_user_id`."""
    return build_user_headers(user_id, "SafeHarborCertifier")


def headers_without_role(user_id: str = "officer-1") -> dict:
    """Headers carrying `X-User-ID` but no `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "ComplianceOfficer") -> dict:
    """Headers carrying `X-User-Role` but no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(
    role: str = "RegulatorAuditor", user_id: str = "auditor-1"
) -> dict:
    """Headers naming a role outside the five the system recognises."""
    return build_user_headers(user_id, role)
