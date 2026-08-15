"""Pre-built role headers for every role in the PRD.

All five roles are opaque identities (PRD section 2.1): X-User-ID is never
compared against any entity id, so shared constants are the canonical form.
Per-instance builders exist so segregation-of-duties tests can pin a specific
X-User-ID for authorize vs dispense, and closure tests can pin the airline
coordinator user.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "ops_controller_headers": build_user_headers("ops-1", "OpsController"),
    "airfield_inspector_headers": build_user_headers("insp-1", "AirfieldInspector"),
    "maintenance_lead_headers": build_user_headers("ml-1", "MaintenanceLead"),
    "airline_coordinator_headers": build_user_headers("al-coord-1",
                                                      "AirlineCoordinator"),
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
}


def make_ops_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OpsController")


def make_airfield_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AirfieldInspector")


def make_maintenance_lead_headers(user_id: str) -> dict:
    """Pin a specific MaintenanceLead X-User-ID (authorize vs dispense)."""
    return build_user_headers(user_id, "MaintenanceLead")


def make_airline_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AirlineCoordinator")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
