"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Associate and Manager are opaque roles: X-User-ID is never compared to any
#    entity id, so the shared constant is the canonical form.
#  - Customer is entity-backed: the shared constant is only a fallback for tests
#    that do NOT exercise ownership (e.g. a 403 that fires regardless of which
#    customer acts). Ownership-gated Customer calls MUST use make_customer_headers.
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "associate_headers": build_user_headers("test-associate-1", "Associate"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# Anonymous request: no auth headers at all (drives ERR_UNAUTHENTICATED).
ANON_HEADERS: dict = {}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the acting
    Customer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "Manager")


def make_associate_headers(user_id: str = "test-associate-1") -> dict:
    return build_user_headers(user_id, "Associate")
