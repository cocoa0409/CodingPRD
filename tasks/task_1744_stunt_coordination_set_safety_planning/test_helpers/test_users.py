"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque user ids used across fixtures. Owner-restricted coordinator
# actions compare X-User-ID against the sequence's recorded coordinator_user_id,
# so every coordinator action in a flow must use the same id.
COORDINATOR_USER_ID = "coord-1"
EXECUTIVE_USER_ID = "exec-1"
SAFETY_USER_ID = "so-1"
DEPARTMENT_HEAD_USER_ID = "dh-1"
SECOND_DEPARTMENT_HEAD_USER_ID = "dh-2"
INSPECTOR_USER_ID = "insp-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "executive_headers": build_user_headers(EXECUTIVE_USER_ID, "ProductionExecutive"),
    "coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "StuntCoordinator"),
    "safety_headers": build_user_headers(SAFETY_USER_ID, "SafetyOfficer"),
    "department_head_headers": build_user_headers(DEPARTMENT_HEAD_USER_ID, "DepartmentHead"),
    "inspector_headers": build_user_headers(INSPECTOR_USER_ID, "EquipmentInspector"),
    # entity_backed:StuntPerformer — fallback for non-ownership tests only.
    "performer_headers": build_user_headers("test-performer-1", "Performer"),
}


def make_performer_headers(user_id: str) -> dict:
    """For Performer (entity-backed: the id of a StuntPerformer). Pass the actual
    StuntPerformer.id as user_id whenever the call is ownership-gated (any write
    whose payload carries performer_id)."""
    return build_user_headers(user_id, "Performer")


def make_coordinator_headers(user_id: str) -> dict:
    """For coordinator-side calls that must act as a different coordinator than
    the canonical one (owner checks compare against coordinator_user_id)."""
    return build_user_headers(user_id, "StuntCoordinator")
