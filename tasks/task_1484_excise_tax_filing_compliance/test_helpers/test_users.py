"""Pre-built role headers for every client-facing role in the PRD (§2.1).

All four roles are opaque (X-User-ID is not tied to any persisted entity), so
shared constants are canonical; per-instance builders exist for tests that
need to control the exact user id (segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "ComplianceAdmin"),
    "analyst_headers": build_user_headers("analyst-1", "TaxAnalyst"),
    "reviewer_headers": build_user_headers("reviewer-1", "TaxReviewer"),
    "auditor_headers": build_user_headers("auditor-1", "JurisdictionAuditor"),
}


def make_admin_headers(user_id: str) -> dict:
    """ComplianceAdmin headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "ComplianceAdmin")


def make_analyst_headers(user_id: str) -> dict:
    """TaxAnalyst headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "TaxAnalyst")


def make_reviewer_headers(user_id: str) -> dict:
    """TaxReviewer headers with a specific X-User-ID (SoD control)."""
    return build_user_headers(user_id, "TaxReviewer")


def make_auditor_headers(user_id: str) -> dict:
    """JurisdictionAuditor headers with a specific X-User-ID."""
    return build_user_headers(user_id, "JurisdictionAuditor")
