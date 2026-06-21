"""Pre-built role headers for every role in the Trophy, Awards & Engraving PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Anonymous, ShopStaff, ShopManager are opaque operator identities: their X-User-ID
#    is never matched against any entity id, so the shared constant is the canonical form.
#  - The Customer shared constant is a fallback for tests that do NOT exercise ownership
#    (e.g. 401/400 checks). For ownership-gated calls, use make_customer_headers(customer_id).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-user", "Anonymous"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "staff_headers": build_user_headers("test-staff-1", "ShopStaff"),
    "manager_headers": build_user_headers("test-manager-1", "ShopManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (the order's customer_id must equal
    the caller's X-User-ID)."""
    return build_user_headers(user_id, "Customer")


def make_staff_headers(user_id: str = "test-staff-1") -> dict:
    """For the ShopStaff role (opaque)."""
    return build_user_headers(user_id, "ShopStaff")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """For the ShopManager role (opaque)."""
    return build_user_headers(user_id, "ShopManager")


def make_anonymous_headers(user_id: str = "anon-user") -> dict:
    """For the Anonymous role (opaque, unauthenticated identity)."""
    return build_user_headers(user_id, "Anonymous")
