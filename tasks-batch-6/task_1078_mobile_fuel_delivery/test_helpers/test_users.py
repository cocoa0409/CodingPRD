"""Pre-built role headers for every role in the Mobile Fuel Delivery PRD.

Six roles (PRD §2.1). Three are opaque operator identifiers (PlatformAdmin,
Dispatcher, BillingOfficer). Driver is an opaque id but ownership is scoped by
route.assigned_driver_id, so driver headers must carry the assigned driver id.
Member and FleetManager are entity_backed:Customer — ownership compares the
resource's customer_id to X-User-ID, so these MUST use the per-instance builders
with the actual Customer.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_headers": build_user_headers("test-billing-1", "BillingOfficer"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only
    # (e.g. 400-on-bad-payload, 404-on-missing-resource, RBAC-denial by role).
    "member_headers": build_user_headers("test-member-1", "Member"),
    "fleet_manager_headers": build_user_headers("test-fleet-1", "FleetManager"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


# ─── Per-instance builders — required for ownership-gated calls ─────────────

def make_member_headers(customer_id: str) -> dict:
    """For Member (entity_backed:Customer). Pass the acting Customer.id whenever the
    call is ownership-gated (own membership / vehicle / order)."""
    return build_user_headers(customer_id, "Member")


def make_fleet_manager_headers(customer_id: str) -> dict:
    """For FleetManager (entity_backed:Customer). Pass the FLEET Customer.id whenever
    the call is ownership-gated (fleet account / fleet vehicle / fleet order)."""
    return build_user_headers(customer_id, "FleetManager")


def make_driver_headers(driver_id: str) -> dict:
    """For Driver. Pass the route's assigned_driver_id; a driver may only execute
    stops on a route whose assigned_driver_id equals X-User-ID."""
    return build_user_headers(driver_id, "Driver")
