"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque ProgramAdmin role, and for tests that
# do not exercise ownership (missing-resource / bad-payload / RBAC-role denials).
TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    # Fallbacks for non-ownership scenarios only; ownership-gated calls must use
    # the per-instance builders below with the real entity id.
    "supervisor_headers": build_user_headers("supervisor-1", "Supervisor"),
    "volunteer_headers": build_user_headers("volunteer-1", "Volunteer"),
}


def make_program_admin_headers(user_id: str = "admin-1") -> dict:
    """ProgramAdmin identity is opaque (PRD 2.1); id is never matched to an entity."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_supervisor_headers(user_id: str) -> dict:
    """For Supervisor (entity_backed:Supervisor). Pass the actual Supervisor.id
    whenever the call is case-ownership-gated (review/approve/close/assign/hearing)."""
    return build_user_headers(user_id, "Supervisor")


def make_volunteer_headers(user_id: str) -> dict:
    """For Volunteer (entity_backed:Volunteer). Pass the actual Volunteer.id
    whenever the call is ownership-gated (visit log, report author, expense submit)."""
    return build_user_headers(user_id, "Volunteer")
