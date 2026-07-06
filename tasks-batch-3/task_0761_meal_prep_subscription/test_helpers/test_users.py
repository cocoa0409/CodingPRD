"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, Anonymous) and for tests that do
# not exercise Customer ownership. The Customer entry here is a fallback for non-ownership use
# only; ownership-gated Customer calls MUST use make_customer_headers(customer_id).
TEST_USERS = {
    # PlatformAdmin: opaque identity, never compared to any entity id.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Anonymous: opaque, unauthenticated public surface.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Customer: shared fallback constant (non-ownership tests only).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (subscription/box/item/pause/plan-change ops)."""
    return build_user_headers(user_id, "Customer")


def make_admin_headers() -> dict:
    """PlatformAdmin headers (opaque identity)."""
    return TEST_USERS["admin_headers"]


def make_anonymous_headers() -> dict:
    """Anonymous headers (opaque identity)."""
    return TEST_USERS["anonymous_headers"]
