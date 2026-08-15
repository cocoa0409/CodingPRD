"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding per PRD §2.1: when X-User-Role is Technician, X-User-ID is the
id of the acting Technician entity; the other four roles carry an opaque
operator identifier not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Technician calls whose
# success does NOT depend on the caller owning the subject resource (the
# shared technician id is not any real entity's id, so never use it for
# ownership-gated calls such as submit / relay-setting authoring / WO start).
TEST_USERS = {
    "ops_manager_headers": build_user_headers("ops-mgr-1", "OperationsManager"),
    "ops_manager_alt_headers": build_user_headers("ops-mgr-2", "OperationsManager"),
    "coordinator_headers": build_user_headers("coord-1", "OutageCoordinator"),
    "supervisor_headers": build_user_headers("sup-1", "SwitchingSupervisor"),
    "supervisor_alt_headers": build_user_headers("sup-2", "SwitchingSupervisor"),
    "compliance_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "technician_headers": build_user_headers("test-tech-1", "Technician"),
}


def make_technician_headers(user_id: str) -> dict:
    """Technician is entity_backed:Technician (PRD §2.1). Pass the actual
    Technician.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Technician")


def make_ops_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OutageCoordinator")


def make_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SwitchingSupervisor")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
