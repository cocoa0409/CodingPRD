"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are `identity: opaque` — X-User-ID is an operator identifier the
server records (onboarded_by_user_id, submitted_by_user_id, reported_by_user_id,
owner_user_id, ...) and compares only for segregation-of-duties; it is never
compared against any entity's id. The shared constants below are therefore
canonical. Use the make_*_headers builders whenever a test needs two distinct
users of the same role (segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "vrm_headers": build_user_headers("test-vrm-1", "VendorRelationshipManager"),
    "risk_officer_headers": build_user_headers("test-ro-1", "RiskOfficer"),
    "business_owner_headers": build_user_headers("test-buo-1", "BusinessUnitOwner"),
    "internal_auditor_headers": build_user_headers("test-aud-1", "InternalAuditor"),
    "compliance_director_headers": build_user_headers("test-cd-1", "ComplianceDirector"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_vrm_headers(user_id: str) -> dict:
    """VendorRelationshipManager headers bound to a specific user id.

    Use a distinct user id from any RiskOfficer approving that manager's
    submission when a segregation-of-duties boundary is under test.
    """
    return build_user_headers(user_id, "VendorRelationshipManager")


def make_risk_officer_headers(user_id: str) -> dict:
    """RiskOfficer headers bound to a specific user id.

    Use for SoD scenarios: the approving officer's X-User-ID must differ from
    the package submitter / plan owner / incident reporter as applicable.
    """
    return build_user_headers(user_id, "RiskOfficer")


def make_business_owner_headers(user_id: str) -> dict:
    """BusinessUnitOwner headers bound to a specific user id.

    Verification and reopen are reporter-gated: pass the same user id that
    filed the incident when a test needs the happy path, and a different one
    when exercising the SoD rejection.
    """
    return build_user_headers(user_id, "BusinessUnitOwner")


def make_internal_auditor_headers(user_id: str) -> dict:
    """InternalAuditor headers bound to a specific user id.

    The auditor must differ from the engagement's started_by_user_id; pass a
    fresh user id distinct from the creating manager's.
    """
    return build_user_headers(user_id, "InternalAuditor")


def make_compliance_director_headers(user_id: str) -> dict:
    """ComplianceDirector headers bound to a specific user id."""
    return build_user_headers(user_id, "ComplianceDirector")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers bound to a specific user id (clock endpoints only)."""
    return build_user_headers(user_id, "PlatformAdmin")
