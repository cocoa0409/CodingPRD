"""Pre-built role headers for every role in the PRD (§2.1).

Roles:
  - Customer:    X-User-ID is the acting Customer entity's id (ownership-checked).
                 Use make_customer_headers(customer_id) for ownership-gated calls.
  - StoreClerk:  opaque operator id, not tied to any entity; acts on any resource.
  - StoreManager: opaque operator id, inventory/financial authority.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (StoreClerk, StoreManager) and for
# tests that do NOT exercise Customer ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "clerk_headers": build_user_headers("test-clerk-1", "StoreClerk"),
    "manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    # entity_backed Customer: shared constant is a fallback for non-ownership tests
    # (e.g. 401/404/422 paths). Ownership-gated Customer calls MUST use the builder.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (booking own reservation, locking/dissolving
    a party the customer coordinates, etc.)."""
    return build_user_headers(user_id, "Customer")


def make_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """StoreClerk is opaque; user_id is not ownership-checked."""
    return build_user_headers(user_id, "StoreClerk")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """StoreManager is opaque; user_id is not ownership-checked."""
    return build_user_headers(user_id, "StoreManager")
