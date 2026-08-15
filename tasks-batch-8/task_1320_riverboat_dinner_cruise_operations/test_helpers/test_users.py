"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. The Customer role is entity_backed (X-User-ID must equal the acting
# Customer record's id), so its shared constant is a fallback for
# non-ownership tests only (e.g. 403/400/404 assertions).
TEST_USERS = {
    "ops_manager_headers": build_user_headers("test-ops-manager-1", "OperationsManager"),
    "captain_headers": build_user_headers("test-captain-1", "Captain"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "charter_agent_headers": build_user_headers("test-charter-agent-1", "CharterSalesAgent"),
    "galley_manager_headers": build_user_headers("test-galley-manager-1", "GalleyManager"),
    "dock_attendant_headers": build_user_headers("test-dock-attendant-1", "DockAttendant"),
}


# Per-instance builders — required for entity_backed roles and for any call
# whose X-User-ID participates in a comparison.

def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id
    whenever the call is ownership-gated (bookings, passengers, credits,
    charter counter/accept/decline)."""
    return build_user_headers(user_id, "Customer")


def make_ops_manager_headers(user_id: str) -> dict:
    """For OperationsManager. Use a distinct user id when a test needs two
    distinguishable operators (e.g. charter-conversion segregation of duties)."""
    return build_user_headers(user_id, "OperationsManager")


def make_charter_agent_headers(user_id: str) -> dict:
    """For CharterSalesAgent with a specific operator id."""
    return build_user_headers(user_id, "CharterSalesAgent")
