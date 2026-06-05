"""Pre-built role headers for every role in the PRD (Section 2.1).

All four roles carry an opaque identity (PRD Section 2.1): X-User-ID is an opaque
operator identifier never compared to an entity's id for ownership. Shared constants
are therefore the canonical form for every role. Tests that must control the exact
operator id (segregation-of-duties checks on life-event approve/reject and dependent
verify) build headers explicitly with make_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "benefits_admin_headers": build_user_headers("admin-1", "BenefitsAdmin"),
    "dependent_verifier_headers": build_user_headers("verifier-1", "DependentVerifier"),
    "payroll_officer_headers": build_user_headers("payroll-1", "PayrollOfficer"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an explicit operator id under a given role.

    Used by segregation-of-duties tests that need the acting X-User-ID to equal or
    differ from a recorded submitter / owning-employee identifier.
    """
    return build_user_headers(user_id, role)


def anonymous_headers() -> dict:
    """Headers with no X-User-ID / X-User-Role, for the unauthenticated path (PRD Section 2.1)."""
    return {"Content-Type": "application/json"}
