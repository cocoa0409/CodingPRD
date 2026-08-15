"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque PlanAdmin role, and for tests that do
# not exercise ownership (400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlanAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (its X-User-ID never equals a real Participant.id).
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}

# Requests carrying no credentials at all (authentication tests).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Participant")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlanAdmin (opaque identity; any user_id works)."""
    return build_user_headers(user_id, "PlanAdmin")
