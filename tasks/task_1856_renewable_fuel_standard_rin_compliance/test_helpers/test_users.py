"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque identities per PRD §2.1: X-User-ID is never compared
against any persisted entity's id. Shared constants are therefore the canonical
form for every role; per-instance builders exist only as a convenience for tests
that want distinct operator ids (e.g., segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "compliance_manager_headers": build_user_headers("test-cm-1", "ComplianceManager"),
    "trader_headers": build_user_headers("test-trader-1", "Trader"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_ops_admin_headers(user_id: str) -> dict:
    """OpsAdmin headers with a specific operator id."""
    return build_user_headers(user_id, "OpsAdmin")


def make_compliance_manager_headers(user_id: str) -> dict:
    """ComplianceManager headers with a specific operator id."""
    return build_user_headers(user_id, "ComplianceManager")


def make_trader_headers(user_id: str) -> dict:
    """Trader headers with a specific operator id."""
    return build_user_headers(user_id, "Trader")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers with a specific operator id (used as auditor_user_id)."""
    return build_user_headers(user_id, "Auditor")
