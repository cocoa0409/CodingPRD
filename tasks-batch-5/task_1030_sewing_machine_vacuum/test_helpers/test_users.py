"""Pre-built role headers for every role in the PRD (§2.1).

SalesAssociate, ServiceTech, and StoreManager carry opaque operator identifiers
not tied to any persisted entity, so a shared constant is the canonical form for
them. Customer's X-User-ID is the id of the acting Customer entity, so its
ownership-gated calls MUST use make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the three opaque operator roles.
TEST_USERS = {
    "sales_associate_headers": build_user_headers("test-sales-associate-1", "SalesAssociate"),
    "service_tech_headers": build_user_headers("test-service-tech-1", "ServiceTech"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    # Fallback for Customer tests that do NOT exercise ownership (e.g. bad role checks).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (repair approve/reject,
    enrollment cancel, subscription cancel)."""
    return build_user_headers(user_id, "Customer")
