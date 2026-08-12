"""Pre-built role headers for every role in the PRD (§2.1).

RegisteredRep is entity-backed: X-User-ID must be the id of the acting
RegisteredRep record, so ownership-gated calls must use make_rep_headers()
with the real rep id. All other roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# rep ownership. The rep_headers entry is a fallback for non-ownership tests.
TEST_USERS = {
    "rep_headers": build_user_headers("test-rep-1", "RegisteredRep"),
    "analyst_headers": build_user_headers("test-analyst-1", "AMLAnalyst"),
    "officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "sar_officer_headers": build_user_headers("test-sar-officer-1", "SAROfficer"),
    "ops_headers": build_user_headers("test-ops-1", "OperationsAnalyst"),
    "auditor_headers": build_user_headers("test-auditor-1", "IndependentAuditor"),
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
}


def make_rep_headers(user_id: str) -> dict:
    """RegisteredRep is entity-backed: pass the actual RegisteredRep.id whenever
    the call creates or touches rep-owned resources (customers, accounts, docs,
    certifications, owners) so the actor resolves to a real, ACTIVE rep."""
    return build_user_headers(user_id, "RegisteredRep")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AMLAnalyst")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_sar_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SAROfficer")


def make_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsAnalyst")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IndependentAuditor")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
