"""Pre-built role headers for every role in the PRD (§2.1).

ComplianceAdmin is an opaque role: the server never compares its X-User-ID to a
persisted entity, so a shared constant is canonical. BSAAnalyst / QAReviewer /
BSAManager are entity-backed roles: X-User-ID must be the id of an existing
Analyst record, so callers MUST build headers with the real Analyst.id via the
per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role — safe to share everywhere.
    "compliance_admin_headers": build_user_headers("test-compliance-admin-1", "ComplianceAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    """BSAAnalyst headers. Pass the actual Analyst.id — the role is entity-backed."""
    return build_user_headers(user_id, "BSAAnalyst")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """QAReviewer headers. Pass the actual Analyst.id — the role is entity-backed."""
    return build_user_headers(user_id, "QAReviewer")


def make_manager_headers(user_id: str) -> dict:
    """BSAManager headers. Pass the actual Analyst.id — the role is entity-backed."""
    return build_user_headers(user_id, "BSAManager")
