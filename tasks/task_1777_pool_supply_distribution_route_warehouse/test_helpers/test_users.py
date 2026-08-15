"""Pre-built role headers for every role in the PRD (§2.1).

Account is entity-backed: for ownership-gated calls (order confirm/cancel/pay,
claim supply-info, RMA creation) the X-User-ID must equal the Account id, so
use make_account_headers(account["id"]) for any call that mutates or reads
account-owned resources. The shared TEST_USERS["account_headers"] entry is
only for tests that do not depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "branch_manager_headers": build_user_headers("test-branch-manager-1", "BranchManager"),
    "counter_rep_headers": build_user_headers("test-counter-rep-1", "CounterRep"),
    "route_dispatcher_headers": build_user_headers("test-route-dispatcher-1", "RouteDispatcher"),
    "warehouse_lead_headers": build_user_headers("test-warehouse-lead-1", "WarehouseLead"),
    # Fallback for non-ownership contexts only; prefer make_account_headers(id).
    "account_headers": build_user_headers("test-account-1", "Account"),
}


def make_account_headers(user_id: str) -> dict:
    """Account is entity-backed by Account: pass the account's id whenever the
    call is ownership-gated (order confirm/cancel/pay, claim supply-info,
    RMA creation, account-owned reads)."""
    return build_user_headers(user_id, "Account")
