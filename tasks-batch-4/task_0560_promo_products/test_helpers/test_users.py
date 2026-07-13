"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (CatalogAdmin, AccountManager,
# ProductionManager whose X-User-ID is never compared to an entity id), and
# for Customer-role tests that do NOT exercise ownership.
TEST_USERS = {
    "catalog_admin_headers": build_user_headers("test-catalog-admin-1", "CatalogAdmin"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "production_manager_headers": build_user_headers("test-production-manager-1", "ProductionManager"),
    # Customer is entity_backed: this shared constant is a fallback for
    # non-ownership tests only; ownership-gated calls must use make_customer_headers.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (create/pay/approve on own order)."""
    return build_user_headers(user_id, "Customer")
