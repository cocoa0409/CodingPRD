"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (StoreManager, PlatformAdmin), and for
# Customer tests that do NOT exercise ownership (e.g. 404/400 on a missing/bad resource,
# or the unauthenticated/forbidden path).
TEST_USERS = {
    # entity_backed:Customer — shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles — shared constant is the canonical form.
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


# Per-instance builders.

def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (placing/cancelling an order, paying a
    subscription, starting a challenge round, etc.)."""
    return build_user_headers(user_id, "Customer")


def make_store_manager_headers(user_id: str = "test-store-manager-1") -> dict:
    """StoreManager is opaque; user_id is not tied to any entity."""
    return build_user_headers(user_id, "StoreManager")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin is opaque; user_id is not tied to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
