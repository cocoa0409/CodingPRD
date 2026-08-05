"""Pre-built role headers.

CourtClerk and ProgramCoordinator are opaque operator identities — a shared constant
is the canonical form. SiteSupervisor and Participant are entity-backed: their
``X-User-ID`` must equal a real Supervisor.id / Participant.id, so ownership-gated calls
MUST use the per-instance builders with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "clerk_headers": build_user_headers("clerk-1", "CourtClerk"),
    "coordinator_headers": build_user_headers("coord-1", "ProgramCoordinator"),
    # A distinct coordinator identity, used as the four-eyes approver (approver != requester).
    "coordinator2_headers": build_user_headers("coord-2", "ProgramCoordinator"),
    # Entity-backed roles — these shared constants are ONLY safe for non-ownership tests
    # (e.g. authentication/enum probes). Ownership-gated calls must use the builders below.
    "supervisor_headers": build_user_headers("supervisor-unbound", "SiteSupervisor"),
    "participant_headers": build_user_headers("participant-unbound", "Participant"),
}


def make_supervisor_headers(supervisor_id: str) -> dict:
    """For SiteSupervisor (entity_backed:Supervisor). Pass the acting Supervisor.id;
    ownership checks compare it to the placement's supervisor_id."""
    return build_user_headers(supervisor_id, "SiteSupervisor")


def make_participant_headers(participant_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the acting Participant.id;
    ownership checks compare it to the referral's participant_id."""
    return build_user_headers(participant_id, "Participant")
