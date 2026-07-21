"""Pre-built role headers for every role in the PRD.

Customer is entity_backed:Customer, so ownership-gated calls acting AS a
customer must use make_customer_headers(customer_id) with the real id.
StoreStaff and StoreManager are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (StoreStaff/StoreManager) and for
# tests whose success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "staff_headers": build_user_headers("staff-op-1", "StoreStaff"),
    "manager_headers": build_user_headers("manager-op-1", "StoreManager"),
    # Fallback for non-ownership Customer tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# A request carrying no auth headers at all (drives ERR_MISSING_AUTH).
ANONYMOUS_HEADERS: dict = {}


def make_customer_headers(user_id: str) -> dict:
    """For role Customer (entity_backed:Customer). Pass the real Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_staff_headers(user_id: str = "staff-op-1") -> dict:
    return build_user_headers(user_id, "StoreStaff")


def make_manager_headers(user_id: str = "manager-op-1") -> dict:
    return build_user_headers(user_id, "StoreManager")
