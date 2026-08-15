"""Pre-built role headers for the three API roles (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. AgentBank is an opaque identity (not tied to any entity),
# so its shared header is canonical. Borrower / ParticipantLender are
# entity-backed: the shared constants below are fallbacks only for tests that
# never exercise an ownership-gated call.
TEST_USERS = {
    "agent_headers": build_user_headers("test-agent-1", "AgentBank"),
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "participant_headers": build_user_headers("test-participant-1", "ParticipantLender"),
}


def make_agent_headers(user_id: str = "test-agent-1") -> dict:
    """AgentBank headers; X-User-ID is an opaque operator id (PRD §2.1)."""
    return build_user_headers(user_id, "AgentBank")


def make_borrower_headers(borrower_id: str) -> dict:
    """Borrower headers; pass the real Borrower.id for ownership-gated calls."""
    return build_user_headers(borrower_id, "Borrower")


def make_participant_headers(participant_id: str) -> dict:
    """ParticipantLender headers; pass the real Participant.id for ownership-gated calls."""
    return build_user_headers(participant_id, "ParticipantLender")
