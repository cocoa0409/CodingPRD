"""Pre-built role headers for every role in the PRD (§2.1).

Contractor is entity_backed by ContractorAccount: X-User-ID must be the acting
ContractorAccount's id, and ownership checks compare resource foreign keys to
it. Every other role is an opaque operator identifier. Ownership-gated calls
MUST use make_contractor_headers(account["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "branch_manager_headers": build_user_headers("test-bm-1", "BranchManager"),
    "sales_rep_headers": build_user_headers("test-sales-1", "SalesRep"),
    "dispatcher_headers": build_user_headers("test-disp-1", "Dispatcher"),
    "credit_analyst_headers": build_user_headers("test-credit-1", "CreditAnalyst"),
    "claims_adjuster_headers": build_user_headers("test-adj-1", "ClaimsAdjuster"),
    "warehouse_clerk_headers": build_user_headers("test-wh-1", "WarehouseClerk"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_branch_manager_headers(user_id: str = "test-bm-1") -> dict:
    return build_user_headers(user_id, "BranchManager")


def make_sales_rep_headers(user_id: str = "test-sales-1") -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_dispatcher_headers(user_id: str = "test-disp-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_credit_analyst_headers(user_id: str = "test-credit-1") -> dict:
    return build_user_headers(user_id, "CreditAnalyst")


def make_claims_adjuster_headers(user_id: str = "test-adj-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_warehouse_clerk_headers(user_id: str = "test-wh-1") -> dict:
    return build_user_headers(user_id, "WarehouseClerk")


def make_contractor_headers(contractor_account_id: str) -> dict:
    """For Contractor (entity_backed:ContractorAccount). Pass the acting
    ContractorAccount.id whenever the call is ownership-gated."""
    return build_user_headers(contractor_account_id, "Contractor")
