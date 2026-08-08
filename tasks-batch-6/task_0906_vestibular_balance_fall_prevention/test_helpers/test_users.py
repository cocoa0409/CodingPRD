"""Pre-built role headers for every role in the PRD.

IntakeCoordinator and ClinicSupervisor are opaque roles (X-User-ID is an
operator identifier the server never compares to any entity). Clinician is
entity_backed: X-User-ID must equal the acting Clinician entity's id for
ownership-gated operations (finalize assessment/reassessment, attend, no-show).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# clinician ownership.
TEST_USERS = {
    "intake_headers": build_user_headers("intake-op-1", "IntakeCoordinator"),
    "supervisor_headers": build_user_headers("supervisor-op-1", "ClinicSupervisor"),
    # Fallback Clinician header for non-ownership scenarios (e.g. 404 / validation
    # failures reached before the ownership check). NEVER use this where a
    # clinician-ownership check must pass — thread make_clinician_headers(id) instead.
    "clinician_headers": build_user_headers("clinician-fallback-1", "Clinician"),
}


def make_clinician_headers(user_id: str) -> dict:
    """For Clinician (entity_backed:Clinician). Pass the actual Clinician.id as
    user_id whenever the call is ownership-gated (assessment/reassessment
    finalize, session attend/no-show) or creates a resource whose clinician_id
    must match a later owner-scoped call."""
    return build_user_headers(user_id, "Clinician")


def make_intake_headers(user_id: str = "intake-op-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_supervisor_headers(user_id: str = "supervisor-op-1") -> dict:
    return build_user_headers(user_id, "ClinicSupervisor")
