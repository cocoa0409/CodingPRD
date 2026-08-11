"""Pre-built role headers for every role in the PRD (§2.1).

Customer is an entity-backed role: X-User-ID must be the acting Customer's id
for ownership-gated calls. Use make_customer_headers(customer_id) for those.
The other four roles use opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constants are the canonical form.
    "customer_service_headers": build_user_headers("test-cs-1", "CustomerService"),
    "operations_manager_headers": build_user_headers("test-om-1", "OperationsManager"),
    "route_planner_headers": build_user_headers("test-rp-1", "RoutePlanner"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed: Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (own record, own orders)."""
    return build_user_headers(user_id, "Customer")


def make_driver_headers(user_id: str) -> dict:
    """Driver with a specific opaque operator id (e.g. for self-override tests)."""
    return build_user_headers(user_id, "Driver")
