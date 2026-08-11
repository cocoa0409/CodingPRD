"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # opaque role: shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
}


# Per-instance builders — required for the entity_backed roles.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (own bikes, own requests, PAY/DISPUTE)."""
    return build_user_headers(user_id, "Customer")


def make_mechanic_headers(user_id: str) -> dict:
    """For Mechanic (entity_backed:Mechanic). Pass the actual Mechanic.id as user_id
    whenever the call is scoped to the assigned mechanic (arrive/start/hold/resume/
    complete/no-show and stop events)."""
    return build_user_headers(user_id, "Mechanic")
