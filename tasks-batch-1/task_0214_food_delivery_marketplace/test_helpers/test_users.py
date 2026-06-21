"""Pre-built role headers for every role in the PRD (§2.1).

Two opaque roles (PlatformAdmin, Support) use shared-constant headers — their
X-User-ID is never matched against a persisted entity.

Three entity-backed roles (Restaurant, Customer, Dasher) MUST thread the real
entity id into X-User-ID whenever the call is ownership-gated. For those, use
the per-instance make_<role>_headers(entity_id) builders. The shared constants
below are safe only for tests that do not exercise ownership (e.g. role-denied
checks, missing-header checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "support_headers": build_user_headers("test-support-1", "Support"),
    # Entity-backed roles — shared constants for NON-ownership tests only.
    "restaurant_headers": build_user_headers("test-restaurant-1", "Restaurant"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "dasher_headers": build_user_headers("test-dasher-1", "Dasher"),
}


# --- Per-instance builders for entity-backed roles ---
def make_restaurant_headers(restaurant_id: str) -> dict:
    """For Restaurant (entity_backed). Pass the actual Restaurant.id when the
    call is ownership-gated (dispatch, menu mutations, deactivate, etc.)."""
    return build_user_headers(restaurant_id, "Restaurant")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed). Pass the actual Customer.id when the call
    is ownership-gated (place/cancel/tip/issue on own order)."""
    return build_user_headers(customer_id, "Customer")


def make_dasher_headers(dasher_id: str) -> dict:
    """For Dasher (entity_backed). Pass the actual Dasher.id when the call is
    ownership-gated (accept/decline/picked-up/delivered own delivery)."""
    return build_user_headers(dasher_id, "Dasher")


def make_admin_headers() -> dict:
    """Opaque PlatformAdmin headers."""
    return build_user_headers("test-admin-1", "PlatformAdmin")


def make_support_headers() -> dict:
    """Opaque Support headers."""
    return build_user_headers("test-support-1", "Support")
