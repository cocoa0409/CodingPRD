"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlanAdministrator"),
    "admin2_headers": build_user_headers("admin-2", "PlanAdministrator"),
    "fiduciary_headers": build_user_headers("fid-1", "IndependentFiduciary"),
    "fiduciary2_headers": build_user_headers("fid-2", "IndependentFiduciary"),
    "recordkeeper_headers": build_user_headers("rk-1", "Recordkeeper"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


# Per-instance builders — required for every entity_backed role.
def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual Participant.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Participant")


def make_admin_headers(user_id: str) -> dict:
    """PlanAdministrator with a specific opaque operator id (e.g., to pin the
    search exhauster's identity for segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "PlanAdministrator")


def make_fiduciary_headers(user_id: str) -> dict:
    """IndependentFiduciary with a specific opaque operator id."""
    return build_user_headers(user_id, "IndependentFiduciary")


def make_recordkeeper_headers(user_id: str) -> dict:
    """Recordkeeper with a specific opaque operator id."""
    return build_user_headers(user_id, "Recordkeeper")
