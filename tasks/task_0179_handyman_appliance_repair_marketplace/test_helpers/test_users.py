"""Pre-built role headers for every role in the PRD (§2.1).

Customer and Pro are entity-backed: ownership checks compare X-User-ID against the
resource's customer/pro foreign key. Tests whose success depends on ownership MUST build
headers with the actual entity id via make_customer_headers / make_pro_headers. The shared
TEST_USERS constants are only safe for opaque roles and for non-ownership tests (e.g.
400-on-bad-payload, 401/403 auth checks, or admin/dispatcher reads).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "pro_headers": build_user_headers("test-pro-1", "Pro"),
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (job/dispute writes)."""
    return build_user_headers(user_id, "Customer")


def make_pro_headers(user_id: str) -> dict:
    """For Pro (entity_backed:Pro). Pass the actual Pro.id as user_id whenever the call
    is ownership-gated (dispatch-window/invoice/visit writes)."""
    return build_user_headers(user_id, "Pro")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is opaque; id is recorded but not ownership-compared."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque, read-only."""
    return build_user_headers(user_id, "Dispatcher")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous is opaque; used for self-registration only."""
    return build_user_headers(user_id, "Anonymous")
