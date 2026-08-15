"""Pre-built role headers for every role in the PRD (§2.1).

FleetAdmin, LoadPlanner, Dispatcher, SafetyOfficer and PayrollClerk are opaque
operator identities; Driver is entity-backed: X-User-ID must be the Driver id
whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Driver ownership.
TEST_USERS = {
    "fleet_admin_headers": build_user_headers("fleet-admin-1", "FleetAdmin"),
    "load_planner_headers": build_user_headers("load-planner-1", "LoadPlanner"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "safety_officer_headers": build_user_headers("safety-officer-1", "SafetyOfficer"),
    "payroll_clerk_headers": build_user_headers("payroll-1", "PayrollClerk"),
    # entity_backed role: fallback for non-ownership reads only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_fleet_admin_headers(user_id: str = "fleet-admin-1") -> dict:
    return build_user_headers(user_id, "FleetAdmin")


def make_load_planner_headers(user_id: str = "load-planner-1") -> dict:
    return build_user_headers(user_id, "LoadPlanner")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_safety_officer_headers(user_id: str = "safety-officer-1") -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_payroll_clerk_headers(user_id: str = "payroll-1") -> dict:
    """PayrollClerk is opaque; distinct user_ids exercise the §3.9
    segregation-of-duties control (approver must differ from creator)."""
    return build_user_headers(user_id, "PayrollClerk")


def make_driver_headers(user_id: str) -> dict:
    """Driver is entity-backed: pass the actual Driver.id whenever the call is
    ownership-gated (duty events, check calls, fuel purchases, accessorials)."""
    return build_user_headers(user_id, "Driver")
