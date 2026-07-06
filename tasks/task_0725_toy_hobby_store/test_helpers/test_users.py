"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "catalog_admin_headers": build_user_headers("test-catalog-admin-1", "CatalogAdmin"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "store_associate_headers": build_user_headers("test-store-associate-1", "StoreAssociate"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # entity_backed Customer: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# Per-instance builder — required for the entity_backed Customer role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (own order / layaway / registry / event)."""
    return build_user_headers(user_id, "Customer")
