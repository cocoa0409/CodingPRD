"""Pre-built role headers for every role in the PRD (§2.1).

The Contractor role is entity-backed: its X-User-ID must be the id of the
acting ContractorAccount. Use make_contractor_headers(account_id) for any
ownership-gated call. The opaque operator roles accept any X-User-ID; the
server records it only where a workflow demands attribution.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque operator roles and for tests that do
# not exercise ownership (400/404/role-denial paths, manager decisions, etc.).
TEST_USERS = {
    "manager_headers": build_user_headers("mgr-1", "BranchManager"),
    "counterrep_headers": build_user_headers("rep-1", "CounterRep"),
    "sales_headers": build_user_headers("sales-1", "InsideSales"),
    "warehouse_headers": build_user_headers("wh-1", "WarehouseLead"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. role-denial probes where no account context matters).
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_manager_headers(user_id: str) -> dict:
    """BranchManager operator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "BranchManager")


def make_counterrep_headers(user_id: str) -> dict:
    """CounterRep operator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "CounterRep")


def make_sales_headers(user_id: str) -> dict:
    """InsideSales operator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "InsideSales")


def make_warehouse_headers(user_id: str) -> dict:
    """WarehouseLead operator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "WarehouseLead")


def make_contractor_headers(account_id: str) -> dict:
    """Contractor headers. Pass the actual ContractorAccount.id whenever the
    call is ownership-gated (quote award, sheet approve, substitute decision,
    account-scoped reads)."""
    return build_user_headers(account_id, "Contractor")
