"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership. ProgramAdmin's identity is opaque: the server does
# not compare it to any entity's id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g., bad-payload 400s, missing-resource 404s).
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ProgramAdmin (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_coach_headers(user_id: str) -> dict:
    """For Coach (entity_backed:Coach). Pass the actual Coach.id as user_id
    whenever the call is ownership-gated (attendance marking, own cases, own
    referrals)."""
    return build_user_headers(user_id, "Coach")


def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id as user_id whenever the call is ownership-gated (self
    registration, own cancels, own deposits, own reads)."""
    return build_user_headers(user_id, "Participant")


# Anonymous headers — no X-User-Role / X-User-ID at all (401 tests).
ANONYMOUS_HEADERS: dict = {}
