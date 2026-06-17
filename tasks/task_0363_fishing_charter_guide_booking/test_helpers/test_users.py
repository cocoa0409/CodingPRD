"""Pre-built role headers for every role in the PRD (§2.1).

DockMaster and FleetManager have opaque identity — X-User-ID is an operator
identifier never matched against a stored entity, so the shared constants are
the canonical form for them.

Captain and Customer are entity_backed — when X-User-Role is Captain, X-User-ID
must equal the acting Captain entity's id; when Customer, it must equal the
acting Customer entity's id. For ownership-gated calls use the make_*_headers()
builders with the actual entity id. The shared constants for these two roles are
only safe for calls whose success does NOT depend on the caller owning the
subject resource (e.g., 403-forbidden-role, 400-bad-payload, 404-missing).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "dock_master_headers": build_user_headers("test-dockmaster-1", "DockMaster"),
    "fleet_manager_headers": build_user_headers("test-fleetmanager-1", "FleetManager"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "captain_headers": build_user_headers("test-captain-shared-id", "Captain"),
    "customer_headers": build_user_headers("test-customer-shared-id", "Customer"),
}


def make_captain_headers(captain_id: str) -> dict:
    """For Captain (entity_backed:Captain). Pass the actual Captain.id as
    captain_id whenever the call is ownership-gated (weather-hold, sail, and
    catch-report on the charter the captain crews)."""
    return build_user_headers(captain_id, "Captain")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated (creating, paying, or
    cancelling one's own booking, or adding an add-on to it)."""
    return build_user_headers(customer_id, "Customer")
