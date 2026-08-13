"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "production_manager_headers": build_user_headers("test-pm-1", "ProductionManager"),
    "warehouse_chief_headers": build_user_headers("test-wh-1", "WarehouseChief"),
    "client_contact_headers": build_user_headers("test-client-1", "ClientContact"),
    # Opaque roles whose X-User-ID is recorded on workflows (SoD/continuity comparisons):
    # use the per-instance builders below whenever the specific identity matters.
    "rigging_supervisor_headers": build_user_headers("rig-1", "RiggingSupervisor"),
    "structural_engineer_headers": build_user_headers("eng-1", "StructuralEngineer"),
    "safety_inspector_headers": build_user_headers("si-1", "SafetyInspector"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "crew_chief_headers": build_user_headers("test-chief-1", "CrewChief"),
}


# Per-instance builders — required whenever the specific X-User-ID value matters.
def make_crew_chief_headers(technician_id: str) -> dict:
    """For CrewChief (entity_backed:Technician). Pass the actual Technician.id as
    technician_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(technician_id, "CrewChief")


def make_rigging_supervisor_headers(user_id: str) -> dict:
    """RiggingSupervisor with a specific recorded identity (SoD reference on points)."""
    return build_user_headers(user_id, "RiggingSupervisor")


def make_structural_engineer_headers(user_id: str) -> dict:
    """StructuralEngineer with a specific identity (SoD checks on approvals)."""
    return build_user_headers(user_id, "StructuralEngineer")


def make_safety_inspector_headers(user_id: str) -> dict:
    """SafetyInspector with a specific identity (inspection continuity checks)."""
    return build_user_headers(user_id, "SafetyInspector")
