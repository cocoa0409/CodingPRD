"""Pre-built role headers for every role in the PRD (§2.1).

Role identity semantics (PRD §2.1): when X-User-Role is SpdTechnician or
SpdSupervisor, X-User-ID must be the id of a persisted Technician (attribution
and standing checks compare entity foreign keys to X-User-ID) — those two
roles therefore expose per-instance builders. FacilityAdmin, OrScheduler and
QualityAuditor are opaque identities, so shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "facility_admin_headers": build_user_headers("test-facility-admin-1", "FacilityAdmin"),
    "or_scheduler_headers": build_user_headers("test-or-scheduler-1", "OrScheduler"),
    "quality_auditor_headers": build_user_headers("test-quality-auditor-1", "QualityAuditor"),
    # Entity-backed fallbacks for NON-ownership calls only (e.g. plain reads).
    # Any state-changing technician/supervisor call MUST use the builders
    # below with the acting Technician's real id.
    "technician_headers": build_user_headers("test-technician-1", "SpdTechnician"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "SpdSupervisor"),
}


def make_technician_headers(technician_id: str) -> dict:
    """SpdTechnician headers bound to a real Technician.id (PRD §2.1)."""
    return build_user_headers(technician_id, "SpdTechnician")


def make_supervisor_headers(technician_id: str) -> dict:
    """SpdSupervisor headers bound to a real Technician.id (PRD §2.1)."""
    return build_user_headers(technician_id, "SpdSupervisor")
