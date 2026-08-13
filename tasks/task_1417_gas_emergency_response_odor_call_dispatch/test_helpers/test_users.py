"""Pre-built role headers for every role in the PRD §2.1.

FieldTechnician is entity_backed: its X-User-ID must be the acting
FieldTechnician record's id whenever the call is ownership-gated
(PRD §2.1). Use make_technician_headers(tech_id) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and non-ownership-gated calls.
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "supervisor2_headers": build_user_headers("test-supervisor-2", "Supervisor"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
    # Fallback for non-ownership technician calls (never for arrive/clear/
    # execute/reading/action/make-safe — those need the real technician id).
    "technician_headers": build_user_headers("test-technician-1", "FieldTechnician"),
}


def make_technician_headers(technician_id: str) -> dict:
    """FieldTechnician is entity_backed: pass the actual FieldTechnician.id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(technician_id, "FieldTechnician")


def make_supervisor_headers(user_id: str) -> dict:
    """Supervisor with a distinct opaque id — used for segregation-of-duties
    drafting/finalizing pairs (PRD §2.1, §3.7)."""
    return build_user_headers(user_id, "Supervisor")
