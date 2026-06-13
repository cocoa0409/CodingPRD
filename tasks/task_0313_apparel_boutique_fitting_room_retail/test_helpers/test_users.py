"""Pre-built role headers for every role in the PRD.

Four roles: Customer (entity-backed — X-User-ID is the acting Customer.id),
plus StoreAssociate, Merchandiser, StoreManager (opaque operator identifiers
not tied to any persisted entity).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - The three opaque roles: shared constant is the canonical form (their
#     X-User-ID is never compared to any entity id).
#   - Customer: shared constant is a fallback for tests that do NOT exercise
#     ownership (e.g., 401/403-role/404 negative cases). For any ownership-gated
#     Customer call, use make_customer_headers(customer["id"]) instead.
TEST_USERS = {
    "store_associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    "merchandiser_headers": build_user_headers("test-merchandiser-1", "Merchandiser"),
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (creating/acting on that
    customer's own holds, appointments, returns, or special orders)."""
    return build_user_headers(user_id, "Customer")


def make_store_associate_headers(user_id: str = "test-associate-1") -> dict:
    return build_user_headers(user_id, "StoreAssociate")


def make_merchandiser_headers(user_id: str = "test-merchandiser-1") -> dict:
    return build_user_headers(user_id, "Merchandiser")


def make_store_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "StoreManager")
