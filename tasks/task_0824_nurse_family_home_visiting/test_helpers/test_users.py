"""Pre-built role headers for every role in the PRD.

Two roles are opaque operator identities (IntakeCoordinator, ProgramAdmin): the
X-User-ID is not compared to any entity, so a shared constant is the canonical form.
Two roles are entity-backed (HomeVisitNurse -> Nurse, Supervisor -> Supervisor):
ownership-gated calls MUST use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - IntakeCoordinator / ProgramAdmin: opaque, always safe.
#  - Nurse / Supervisor: shared constant is a fallback for NON-ownership tests
#    only (e.g. RBAC-denial, 404-on-missing). Ownership-gated calls must use the
#    make_*_headers builders below with the actual entity id.
TEST_USERS = {
    "intake_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "nurse_headers": build_user_headers("test-nurse-1", "HomeVisitNurse"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
}


def make_nurse_headers(user_id: str) -> dict:
    """For HomeVisitNurse (entity_backed:Nurse). Pass the acting Nurse.id whenever
    the call is ownership-gated (visit complete/revert/mark-missed/reschedule)."""
    return build_user_headers(user_id, "HomeVisitNurse")


def make_supervisor_headers(user_id: str) -> dict:
    """For Supervisor (entity_backed:Supervisor). Pass the acting Supervisor.id
    whenever the call is ownership-gated (signing a supervision session)."""
    return build_user_headers(user_id, "Supervisor")


def make_intake_headers(user_id: str = "test-intake-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")
