"""Pre-built role headers for every role in the PRD (section 2.1).

`Anonymous`, `SiteOperator`, and `NetworkAdmin` are opaque roles: X-User-ID is
never compared to any entity id, so shared constants are their canonical form.

`Driver` and `FleetManager` are entity-backed: X-User-ID must equal the acting
Driver.id / FleetAccount.id on ownership-gated calls. The shared constants are
fallbacks for non-ownership tests only; fixtures and tests must use
make_driver_headers(entity_id) / make_fleet_manager_headers(entity_id)
whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles: canonical shared constants
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "site_operator_headers": build_user_headers("op-alice", "SiteOperator"),
    "network_admin_headers": build_user_headers("admin-1", "NetworkAdmin"),
    # entity_backed roles: fallbacks for non-ownership tests only
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "fleet_manager_headers": build_user_headers("test-fleet-1", "FleetManager"),
}


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity-backed): pass the actual Driver.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Driver")


def make_fleet_manager_headers(user_id: str) -> dict:
    """For FleetManager (entity-backed): pass the actual FleetAccount.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FleetManager")


def make_site_operator_headers(user_id: str) -> dict:
    """For SiteOperator (opaque): pins a specific operator identifier, e.g. for
    incident segregation-of-duties scenarios."""
    return build_user_headers(user_id, "SiteOperator")


def make_network_admin_headers(user_id: str) -> dict:
    """For NetworkAdmin (opaque)."""
    return build_user_headers(user_id, "NetworkAdmin")


def make_anonymous_headers(user_id: str) -> dict:
    """For Anonymous (opaque)."""
    return build_user_headers(user_id, "Anonymous")
