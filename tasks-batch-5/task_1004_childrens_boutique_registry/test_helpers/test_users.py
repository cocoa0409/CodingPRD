"""Pre-built role headers for every role in the PRD.

Customer is the sole entity_backed role — its X-User-ID must equal the acting
Customer's id for ownership-gated calls (activate/archive/add-item to a
registry, pay/cancel an order, cancel a special order). Use make_customer_headers()
with the real Customer.id for those calls. The shared TEST_USERS["customer_headers"]
constant is only safe for calls whose success does NOT depend on ownership
(e.g., a 401/403 auth denial, a 422 bad-payload, a 404 missing-resource).

Anonymous, StoreStaff, and PlatformAdmin are opaque roles; their shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-shared-id", "Customer"),
    # opaque roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("test-anonymous", "Anonymous"),
    "store_staff_headers": build_user_headers("test-store-staff", "StoreStaff"),
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    # Header carrying an unrecognized role, for ERR_UNAUTHENTICATED tests.
    "unknown_role_headers": build_user_headers("test-unknown", "Stranger"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated or the acting principal
    must resolve to a real customer (registry activate/archive/items/gifts,
    order create/pay/cancel, consignment/trade-in/special-order create)."""
    return build_user_headers(customer_id, "Customer")


def make_store_staff_headers(user_id: str = "test-store-staff") -> dict:
    """StoreStaff is opaque; user_id is not treated as a foreign key."""
    return build_user_headers(user_id, "StoreStaff")


def make_platform_admin_headers(user_id: str = "test-platform-admin") -> dict:
    """PlatformAdmin is opaque; user_id is not treated as a foreign key."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "test-anonymous") -> dict:
    """Anonymous is opaque; used for customer registration and public reads."""
    return build_user_headers(user_id, "Anonymous")
