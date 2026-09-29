"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator identifier, so the shared
constants below are the canonical form for them. The Driver role is backed by
the Driver entity: its ``X-User-ID`` must equal the acting driver's ``id``, so
ownership-gated Driver calls MUST use ``make_driver_headers(driver["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities: the shared constant is the canonical form.
    "fleet_planner_headers": build_user_headers("op-planner-1", "FleetPlanner"),
    "transport_manager_headers": build_user_headers("op-transport-1", "TransportManager"),
    "payroll_analyst_headers": build_user_headers("op-payroll-1", "PayrollAnalyst"),
    "safety_manager_headers": build_user_headers("op-safety-1", "SafetyManager"),
    "maintenance_coordinator_headers": build_user_headers(
        "op-maintenance-1", "MaintenanceCoordinator"
    ),
    # Driver is entity-backed: this constant is only for tests that never reach
    # an ownership check (for example unauthorized-role probes).
    "driver_headers": build_user_headers("op-driver-1", "Driver"),
}

# Distinct operator identifiers for segregation-of-duties scenarios.
OPERATOR_U1 = "U1"
OPERATOR_U2 = "U2"
OPERATOR_U3 = "U3"
OPERATOR_U5 = "U5"
OPERATOR_U9 = "U9"


def make_driver_headers(driver_id: str) -> dict:
    """Headers for the Driver role. ``driver_id`` must be the acting Driver's id."""
    return build_user_headers(driver_id, "Driver")


def make_fleet_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetPlanner")


def make_transport_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransportManager")


def make_payroll_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayrollAnalyst")


def make_safety_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyManager")


def make_maintenance_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaintenanceCoordinator")


def headers_without_role(user_id: str = "op-anonymous-1") -> dict:
    """Identity headers with no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(role: str = "FleetAdmin") -> dict:
    """Identity headers naming a role that is not one of the six declared roles."""
    return build_user_headers("op-unknown-1", role)


def headers_without_user_id(role: str = "Driver") -> dict:
    """Role headers with no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
