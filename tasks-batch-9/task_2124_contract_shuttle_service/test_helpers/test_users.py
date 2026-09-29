"""Pre-built auth headers for every persona the PRD recognises.

For `ContractAdmin`, `ClientLiaison`, `OpsPlanner` and `FleetManager` the
`X-User-ID` is an opaque operator identifier that is never compared to any
entity's id, so the shared constants below are always safe. For `DriverUser`
the `X-User-ID` is the id of the acting `Driver` row and ownership checks
compare it to the trip's `driver_id`, so driver-facing calls MUST use
`make_driver_headers(driver["id"])`.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "contract_admin_headers": build_user_headers("admin-1", "ContractAdmin"),
    "client_liaison_headers": build_user_headers("liaison-1", "ClientLiaison"),
    "ops_planner_headers": build_user_headers("planner-1", "OpsPlanner"),
    "fleet_manager_headers": build_user_headers("fleet-1", "FleetManager"),
    # Fallback only — never use for a call whose success depends on the caller
    # owning the trip.
    "driver_user_headers": build_user_headers("driver-1", "DriverUser"),
}

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_driver_headers(driver_id: str) -> dict:
    """Headers for a DriverUser. Pass the real Driver id: the server compares
    `X-User-ID` against the trip's `driver_id`."""
    return build_user_headers(driver_id, "DriverUser")


def make_contract_admin_headers(user_id: str) -> dict:
    """Headers for a specific ContractAdmin principal, for segregation-of-duties."""
    return build_user_headers(user_id, "ContractAdmin")


def make_client_liaison_headers(user_id: str) -> dict:
    """Headers for a specific ClientLiaison principal, for segregation-of-duties."""
    return build_user_headers(user_id, "ClientLiaison")


def make_ops_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OpsPlanner")


def make_fleet_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetManager")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary role string, including unrecognised roles."""
    return build_user_headers(user_id, role)
