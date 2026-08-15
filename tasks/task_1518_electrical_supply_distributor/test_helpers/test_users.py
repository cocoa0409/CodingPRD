"""Pre-built role headers for every role in the PRD.

Six roles are opaque (X-User-ID is an operator identifier never compared to
any entity id, PRD section 2.1); their shared constants are the canonical
form. Contractor is entity-backed: X-User-ID must equal the owning
Contractor's id for ownership-gated calls, so make_contractor_headers() must
be used with the real contractor id whenever ownership is exercised.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "branch_manager_headers": build_user_headers("test-branch-manager-1", "BranchManager"),
    "credit_manager_headers": build_user_headers("test-credit-manager-1", "CreditManager"),
    "warehouse_manager_headers": build_user_headers("test-warehouse-manager-1", "WarehouseManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "rebate_clerk_headers": build_user_headers("test-rebate-clerk-1", "RebateClerk"),
    # Fallback only for calls that do not exercise ownership (e.g. reads).
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_branch_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BranchManager")


def make_credit_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditManager")


def make_warehouse_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseManager")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_rebate_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RebateClerk")


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity-backed). Pass the actual Contractor.id as
    user_id whenever the call is ownership-gated (release create/cancel)."""
    return build_user_headers(user_id, "Contractor")
