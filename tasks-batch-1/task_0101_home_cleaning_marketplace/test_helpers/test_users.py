"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon", "Anonymous"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "cleaner_headers": build_user_headers("test-cleaner-1", "Cleaner"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_cleaner_headers(user_id: str) -> dict:
    """For Cleaner (entity_backed:Cleaner). Pass the actual Cleaner.id as user_id
    whenever the call is ownership-gated (e.g. completing a booking)."""
    return build_user_headers(user_id, "Cleaner")


def make_admin_headers() -> dict:
    """For PlatformAdmin (opaque). The id is never compared to any entity."""
    return TEST_USERS["platform_admin_headers"]


def make_anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
