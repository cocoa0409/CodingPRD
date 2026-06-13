"""Pre-built role headers for every role in the PRD.

Customer is an entity-backed role: X-User-ID must equal the acting Customer's id
for ownership-gated calls. The other three roles (Dispatcher, ServiceManager,
Billing) are opaque operators whose X-User-ID is never matched against an entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# customer ownership (e.g. 401/403/404 checks, ServiceManager superset calls).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "service_manager_headers": build_user_headers("test-service-manager-1", "ServiceManager"),
    "billing_headers": build_user_headers("test-billing-1", "Billing"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (creating/mutating that
    customer's jobs, rooms, add-ons, plans, claims)."""
    return build_user_headers(user_id, "Customer")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_service_manager_headers(user_id: str = "test-service-manager-1") -> dict:
    return build_user_headers(user_id, "ServiceManager")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "Billing")
