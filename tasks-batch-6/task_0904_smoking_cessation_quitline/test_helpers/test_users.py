"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ProgramAdmin, CaseManager) whose
# X-User-ID is never compared to a persisted entity, and for non-ownership tests.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    # Fallback Participant constant for tests that do not exercise ownership.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}

# Headers with no auth at all — for the unauthenticated-request test.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_participant_headers(user_id: str) -> dict:
    """For the entity-backed Participant role. Pass the actual Participant.id as
    user_id whenever the call is ownership-gated (the server compares X-User-ID
    to the participant linkage of the resource)."""
    return build_user_headers(user_id, "Participant")
