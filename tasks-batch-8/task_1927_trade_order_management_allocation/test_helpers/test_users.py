"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are opaque operator identities: `X-User-ID` is never compared to
any entity's `id` for ownership — the single place it is compared is the
segregation-of-duties check at plan approval. Shared constants are therefore
the canonical form for every role; ad-hoc ids are built inline with the
framework's build_user_headers where a test needs a specific identity.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "trader_headers": build_user_headers("trader-1", "Trader"),
    "execution_desk_headers": build_user_headers("exec-1", "ExecutionDesk"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "settlement_ops_headers": build_user_headers("ops-1", "SettlementOps"),
    "desk_admin_headers": build_user_headers("admin-1", "DeskAdmin"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}

# A request missing X-User-ID / X-User-Role (PRD §2.1 -> ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
