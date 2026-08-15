"""Pre-built role headers for every role in the PRD.

Renter is entity-backed: when X-User-Role is Renter, X-User-ID must be the id
of the acting Renter entity, so ownership-gated calls MUST be made with
make_renter_headers(renter_id) built from the real Renter id. DockStaff,
FleetManager and Mechanic are opaque operator identities; the shared constants
are their canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g. POST /renters self-registration, 401/403 checks).
    "renter_headers": build_user_headers("test-renter-1", "Renter"),
    # opaque roles: shared constants are the canonical form.
    "dock_staff_headers": build_user_headers("test-dock-staff-1", "DockStaff"),
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
}


def make_renter_headers(renter_id: str) -> dict:
    """For Renter (entity_backed:Renter). Pass the actual Renter.id whenever
    the call is ownership-gated (bookings, itinerary, orientation, incidents,
    renter subroutes)."""
    return build_user_headers(renter_id, "Renter")


def make_dock_staff_headers(user_id: str = "test-dock-staff-1") -> dict:
    return build_user_headers(user_id, "DockStaff")


def make_fleet_manager_headers(user_id: str = "test-fleet-manager-1") -> dict:
    return build_user_headers(user_id, "FleetManager")


def make_mechanic_headers(user_id: str = "test-mechanic-1") -> dict:
    return build_user_headers(user_id, "Mechanic")
