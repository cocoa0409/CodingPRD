"""Pre-built role headers for every role in the PRD (§2.1).

The system recognizes exactly four roles, all carrying an OPAQUE identity:
StationManager, Inspector, Receptionist, StateAuditor. Because X-User-ID is
never compared against any entity's id (there are no per-user ownership checks),
the shared-constant headers below are sufficient for every test; no
per-instance entity_backed builder is needed.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "station_manager_headers": build_user_headers("test-station-manager-1", "StationManager"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "receptionist_headers": build_user_headers("test-receptionist-1", "Receptionist"),
    "state_auditor_headers": build_user_headers("test-state-auditor-1", "StateAuditor"),
}


def make_station_manager_headers(user_id: str = "test-station-manager-1") -> dict:
    return build_user_headers(user_id, "StationManager")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")


def make_receptionist_headers(user_id: str = "test-receptionist-1") -> dict:
    return build_user_headers(user_id, "Receptionist")


def make_state_auditor_headers(user_id: str = "test-state-auditor-1") -> dict:
    return build_user_headers(user_id, "StateAuditor")
