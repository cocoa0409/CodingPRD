"""Pre-built role headers for every role in the PRD.

Customer is entity-backed: for ownership-gated calls the X-User-ID must equal
the CustomerAccount id, so use make_customer_headers(customer["id"]) for any
call that mutates or reads customer-owned resources. The shared
TEST_USERS["customer_headers"] entry is only for tests that do not depend on
the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "catalog_manager_headers": build_user_headers("test-catalog-manager-1", "CatalogManager"),
    "inventory_clerk_headers": build_user_headers("test-inventory-clerk-1", "InventoryClerk"),
    "quality_manager_headers": build_user_headers("test-quality-manager-1", "QualityManager"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    # Fallback for non-ownership contexts only; prefer make_customer_headers(id).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed by CustomerAccount: pass the account's id
    whenever the call is ownership-gated (order submit/cancel/reallocate,
    reservation release, standing-order management, consignment consumption)."""
    return build_user_headers(user_id, "Customer")
