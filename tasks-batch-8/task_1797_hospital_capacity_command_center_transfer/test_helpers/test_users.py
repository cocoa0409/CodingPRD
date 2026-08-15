"""Pre-built role headers for every role in the PRD.

All roles except AcceptingPhysician are opaque identities: X-User-ID is not
tied to any persisted entity. AcceptingPhysician is entity-backed by
Physician (X-User-ID is the acting Physician's id); ownership-gated
consult-response calls MUST use make_accepting_physician_headers() with the
real Physician id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "sysadmin_headers": build_user_headers("test-sysadmin-1", "SystemAdministrator"),
    "bed_manager_headers": build_user_headers("bm_1", "BedManager"),
    "coordinator_headers": build_user_headers("coord_1", "TransferCenterCoordinator"),
    "house_supervisor_headers": build_user_headers("hs_1", "HouseSupervisor"),
    "capacity_planner_headers": build_user_headers("cp_1", "CapacityPlanner"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g., role-denial checks on exclusive endpoints).
    "accepting_physician_headers": build_user_headers("test-phys-1", "AcceptingPhysician"),
    # Convenience alternates for segregation-of-duties and ownership tests.
    "house_supervisor_2_headers": build_user_headers("hs_2", "HouseSupervisor"),
    "house_supervisor_3_headers": build_user_headers("hs_3", "HouseSupervisor"),
    "bed_manager_2_headers": build_user_headers("bm_2", "BedManager"),
    "coordinator_2_headers": build_user_headers("coord_2", "TransferCenterCoordinator"),
}


def make_sysadmin_headers(user_id: str = "test-sysadmin-1") -> dict:
    return build_user_headers(user_id, "SystemAdministrator")


def make_bed_manager_headers(user_id: str) -> dict:
    """For BedManager (opaque). Use a distinct user id whenever segregation of
    duties requires the completer to differ from the assignment creator."""
    return build_user_headers(user_id, "BedManager")


def make_coordinator_headers(user_id: str) -> dict:
    """For TransferCenterCoordinator (opaque). The id is recorded as
    intake_coordinator_id / created_by_user_id; pick a stable id per scenario."""
    return build_user_headers(user_id, "TransferCenterCoordinator")


def make_accepting_physician_headers(physician_id: str) -> dict:
    """For AcceptingPhysician (entity_backed:Physician). Pass the acting
    Physician.id whenever the call is ownership-gated (consult-response)."""
    return build_user_headers(physician_id, "AcceptingPhysician")


def make_house_supervisor_headers(user_id: str) -> dict:
    """For HouseSupervisor (opaque). Segregation of duties requires the
    lifting supervisor's id to differ from the declaring supervisor's id."""
    return build_user_headers(user_id, "HouseSupervisor")


def make_capacity_planner_headers(user_id: str = "cp_1") -> dict:
    return build_user_headers(user_id, "CapacityPlanner")
