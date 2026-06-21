"""Pre-built role headers for every role in the PRD.

All three roles carry an opaque identity (PRD §2.1): X-User-ID is an opaque
operator identifier never compared to an entity's id. The shared constants below
are therefore the canonical form for every role. The only identity comparison in
the system is segregation-of-duties between two operator identifiers, so tests
that exercise it use the per-user-id builders to control the exact X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "hr_reviewer_headers": build_user_headers("hr-reviewer-1", "HRReviewer"),
    "everify_operator_headers": build_user_headers("everify-operator-1", "EVerifyOperator"),
    "compliance_officer_headers": build_user_headers("compliance-officer-1", "ComplianceOfficer"),
}


def make_hr_reviewer_headers(user_id: str) -> dict:
    """HRReviewer headers with an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "HRReviewer")


def make_everify_operator_headers(user_id: str) -> dict:
    """EVerifyOperator headers with an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "EVerifyOperator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "ComplianceOfficer")
