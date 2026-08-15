"""Pre-built role headers for every role in the PRD.

All eight roles are opaque identities (PRD §2.1): `X-User-ID` is not tied to
any persisted entity and the server never compares it to an entity id for
ownership checks. Shared constants are therefore the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "terminal_manager_headers": build_user_headers("test-tm-1", "TerminalManager"),
    "pool_administrator_headers": build_user_headers("test-pa-1", "PoolAdministrator"),
    "yard_planner_headers": build_user_headers("test-yp-1", "YardPlanner"),
    "rail_coordinator_headers": build_user_headers("test-rc-1", "RailCoordinator"),
    "gate_supervisor_headers": build_user_headers("test-gs-1", "GateSupervisor"),
    "gate_clerk_headers": build_user_headers("test-gc-1", "GateClerk"),
    "maintenance_planner_headers": build_user_headers("test-mp-1", "MaintenancePlanner"),
    "billing_clerk_headers": build_user_headers("test-bc-1", "BillingClerk"),
}


def make_terminal_manager_headers(user_id: str = "test-tm-1") -> dict:
    return build_user_headers(user_id, "TerminalManager")


def make_pool_administrator_headers(user_id: str = "test-pa-1") -> dict:
    return build_user_headers(user_id, "PoolAdministrator")


def make_yard_planner_headers(user_id: str = "test-yp-1") -> dict:
    return build_user_headers(user_id, "YardPlanner")


def make_rail_coordinator_headers(user_id: str = "test-rc-1") -> dict:
    return build_user_headers(user_id, "RailCoordinator")


def make_gate_supervisor_headers(user_id: str = "test-gs-1") -> dict:
    return build_user_headers(user_id, "GateSupervisor")


def make_gate_clerk_headers(user_id: str = "test-gc-1") -> dict:
    return build_user_headers(user_id, "GateClerk")


def make_maintenance_planner_headers(user_id: str = "test-mp-1") -> dict:
    return build_user_headers(user_id, "MaintenancePlanner")


def make_billing_clerk_headers(user_id: str = "test-bc-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")
