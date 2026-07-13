"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - CatalogAdmin and WarehouseAgent are opaque roles: the server never compares
#     X-User-ID to any entity id, so a shared constant is the canonical form.
#   - The Customer shared constant is a fallback for tests that do NOT exercise
#     ownership (e.g. header-missing / role-denied cases). Ownership-gated Customer
#     calls MUST use make_customer_headers(customer_id) instead.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CatalogAdmin"),
    "warehouse_headers": build_user_headers("test-warehouse-1", "WarehouseAgent"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the entity_backed Customer role. Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (orders, rentals, subscriptions, buyback quotes)."""
    return build_user_headers(user_id, "Customer")
