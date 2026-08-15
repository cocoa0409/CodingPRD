"""Pre-built role headers for every role in the PRD (section 2.1).

PlatformAdmin, CatalogManager, WarehouseOps and CustomerService are opaque roles:
X-User-ID is an operator identifier never compared to any entity id, so the
shared constants are canonical.

Buyer and AccountApprover are entity-backed roles: X-User-ID must be the id of
the acting Account, so any ownership-gated call MUST use make_buyer_headers /
make_approver_headers with the real account id. The shared buyer/approver
constants exist only for negative tests that never reach an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "catalog_manager_headers": build_user_headers("test-catalog-1", "CatalogManager"),
    "warehouse_ops_headers": build_user_headers("test-warehouse-1", "WarehouseOps"),
    "customer_service_headers": build_user_headers("test-service-1", "CustomerService"),
    # Fallbacks for non-ownership tests only — prefer the builders below.
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "approver_headers": build_user_headers("test-approver-1", "AccountApprover"),
}


def make_buyer_headers(account_id: str) -> dict:
    """Buyer is entity-backed by Account: X-User-ID must be the Account id."""
    return build_user_headers(account_id, "Buyer")


def make_approver_headers(account_id: str) -> dict:
    """AccountApprover is entity-backed by Account: X-User-ID must be the Account id."""
    return build_user_headers(account_id, "AccountApprover")
