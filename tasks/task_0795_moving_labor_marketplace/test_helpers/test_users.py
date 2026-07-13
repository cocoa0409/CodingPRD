"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - Dispatcher and Admin are opaque operator identities: the shared constant IS the
#     canonical form (their X-User-ID is never compared to any entity id).
#   - Customer and Helper are entity_backed: the shared constant is a fallback usable ONLY
#     by tests that do not exercise ownership (e.g. 401/403/404 negatives). Ownership-gated
#     calls MUST use the per-instance builders below with the real entity id.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "Admin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "helper_headers": build_user_headers("test-helper-1", "Helper"),
}


def make_customer_headers(user_id: str) -> dict:
    """For a Customer (entity_backed:Customer). Pass the real Customer.id whenever the call
    is ownership-gated (creating/quoting/booking/cancelling a job, filing claims/ratings)."""
    return build_user_headers(user_id, "Customer")


def make_helper_headers(user_id: str) -> dict:
    """For a Helper (entity_backed:Helper). Pass the real Helper.id whenever the call is
    ownership-gated (checking in/out of an assignment the helper owns)."""
    return build_user_headers(user_id, "Helper")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    """For a Dispatcher (opaque operator). Identity is not entity-bound."""
    return build_user_headers(user_id, "Dispatcher")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """For an Admin (opaque operator). Identity is not entity-bound."""
    return build_user_headers(user_id, "Admin")
