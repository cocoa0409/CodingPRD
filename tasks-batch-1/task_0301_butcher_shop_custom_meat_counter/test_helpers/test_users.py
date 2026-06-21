"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly five roles: Customer, CounterClerk, Butcher,
ShiftManager, SafetyOfficer. Only Customer is entity-backed (X-User-ID is the
acting Customer's id); the other four are opaque operators.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the four opaque operator roles, and for tests that
# do not exercise Customer ownership.
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "counter_clerk_headers": build_user_headers("test-clerk-1", "CounterClerk"),
    "butcher_headers": build_user_headers("test-butcher-1", "Butcher"),
    "shift_manager_headers": build_user_headers("test-manager-1", "ShiftManager"),
    "safety_officer_headers": build_user_headers("test-safety-1", "SafetyOfficer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the entity-backed Customer role. Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (placing/cancelling own orders
    or claims)."""
    return build_user_headers(user_id, "Customer")
