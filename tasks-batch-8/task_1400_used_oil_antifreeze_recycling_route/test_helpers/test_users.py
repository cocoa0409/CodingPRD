"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles
    "route_planner_headers": build_user_headers("test-planner-1", "RoutePlanner"),
    "lab_tech_headers": build_user_headers("test-labtech-1", "LabTech"),
    "settlement_clerk_headers": build_user_headers("test-clerk-1", "SettlementClerk"),
    "ehs_officer_headers": build_user_headers("test-ehs-1", "EHSOfficer"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
    "tank_installer_headers": build_user_headers("test-installer-1", "TankInstaller"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


# Per-instance builder — required for Driver (entity_backed:Driver).
def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Driver")
