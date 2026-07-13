"""Pre-built role headers for every role in the PRD.

Three roles carry an opaque X-User-ID that the server never compares to any
entity id (CenterAdmin, Coordinator, Auditor) — for these the shared constant
is the canonical form. The Participant role is entity-backed: its X-User-ID is
the id of the acting Participant entity (PRD 2.1), so a per-instance builder is
mandatory for any ownership-gated self-service write (signup, reservation,
transport request, and their cancels, plus reading own resources).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the opaque roles; safe for Participant only
# on tests that do not exercise the entity-backed ownership identity.
TEST_USERS = {
    "center_admin_headers": build_user_headers("admin-001", "CenterAdmin"),
    "coordinator_headers": build_user_headers("coordinator-001", "Coordinator"),
    "auditor_headers": build_user_headers("auditor-001", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "participant_headers": build_user_headers("participant-fallback-001", "Participant"),
}


def make_participant_headers(participant_id: str) -> dict:
    """For the Participant role (entity_backed:Participant). Pass the actual
    Participant.id as the X-User-ID whenever the call is ownership-gated: a
    self-service signup, meal reservation, transport request, or their cancels,
    and reads of own resources (PRD 2.1)."""
    return build_user_headers(participant_id, "Participant")
