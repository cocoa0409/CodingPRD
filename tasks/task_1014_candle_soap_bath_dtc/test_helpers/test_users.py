"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - MerchOps and PlatformAdmin are opaque roles: X-User-ID is never compared to
#    any entity id, so the shared constant is the canonical form.
#  - Customer is entity_backed:Customer: the shared constant is ONLY a fallback for
#    tests that do NOT exercise ownership (e.g. a 401/403 that fires regardless of
#    which customer acts). Every ownership-gated Customer call MUST use
#    make_customer_headers(customer_id) with the acting Customer's real id.
TEST_USERS = {
    "merchops_headers": build_user_headers("test-merchops-1", "MerchOps"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# Anonymous request: no auth headers at all (drives ERR_UNAUTHENTICATED).
ANON_HEADERS: dict = {}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the acting Customer.id
    as user_id whenever the call is ownership-gated (orders, lines, checkout,
    cancel, returns, subscriptions)."""
    return build_user_headers(user_id, "Customer")


def make_merchops_headers(user_id: str = "test-merchops-1") -> dict:
    return build_user_headers(user_id, "MerchOps")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
