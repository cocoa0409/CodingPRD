"""Pre-built role headers for every role in the PRD.

Two patterns:
- TEST_USERS shared constants — for opaque roles (Dispatcher, PlatformAdmin) and for
  tests that do not exercise ownership (e.g. missing-resource / bad-payload paths).
- make_<role>_headers(id) — required for entity_backed roles (Customer, Mechanic,
  FleetManager). The id passed must be the actual entity id so ownership checks pass.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed roles — shared constants are fallbacks for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
    "fleet_manager_headers": build_user_headers("test-fleet-1", "FleetManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id."""
    return build_user_headers(user_id, "Customer")


def make_mechanic_headers(user_id: str) -> dict:
    """For Mechanic (entity_backed:Mechanic). Pass the actual Mechanic.id."""
    return build_user_headers(user_id, "Mechanic")


def make_fleet_manager_headers(user_id: str) -> dict:
    """For FleetManager (entity_backed:FleetAccount). Pass the actual FleetAccount.id."""
    return build_user_headers(user_id, "FleetManager")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """For Dispatcher (opaque). Any operator id works."""
    return build_user_headers(user_id, "Dispatcher")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque). Any operator id works."""
    return build_user_headers(user_id, "PlatformAdmin")
