"""Pre-built role headers for the seven roles declared in PRD §2.1.

All roles use opaque operator identities (PRD §2.1): X-User-ID is never
compared to any entity id; segregation-of-duties checks compare it against
recorded operator fields such as created_by_user_id / claimed_by_user_id.
The shared constants are canonical for every call; use the make_*_headers
builders when a test needs a specific operator id (e.g. SoD pairs).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "contract_analyst_headers": build_user_headers("test-contract-analyst-1", "ContractAnalyst"),
    "contract_manager_headers": build_user_headers("test-contract-manager-1", "ContractManager"),
    "revenue_integrity_analyst_headers": build_user_headers(
        "test-revenue-integrity-analyst-1", "RevenueIntegrityAnalyst"
    ),
    "recovery_manager_headers": build_user_headers("test-recovery-manager-1", "RecoveryManager"),
    "finance_director_headers": build_user_headers("test-finance-director-1", "FinanceDirector"),
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_contract_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractAnalyst")


def make_contract_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_revenue_integrity_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RevenueIntegrityAnalyst")


def make_recovery_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecoveryManager")


def make_finance_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceDirector")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
