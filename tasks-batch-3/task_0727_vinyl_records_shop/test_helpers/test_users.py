"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque operator roles, and for tests that don't
# exercise Customer ownership (e.g., 400/404/403-forbidden cases).
#
# StoreClerk, Grader, and Manager have opaque X-User-IDs not tied to any entity,
# so the shared constant is the canonical form for them. The Customer entry is a
# fallback for non-ownership tests only; ownership-gated Customer calls MUST use
# make_customer_headers(customer_id) with the real Customer.id.
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "store_clerk_headers": build_user_headers("test-clerk-1", "StoreClerk"),
    "grader_headers": build_user_headers("test-grader-1", "Grader"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (orders, trade-ins, pre-orders,
    grading disputes, special orders, consignments owned by the consignor)."""
    return build_user_headers(user_id, "Customer")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "Manager")


def make_store_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "StoreClerk")


def make_grader_headers(user_id: str = "test-grader-1") -> dict:
    return build_user_headers(user_id, "Grader")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
