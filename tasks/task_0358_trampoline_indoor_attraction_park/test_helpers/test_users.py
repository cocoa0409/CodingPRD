"""Pre-built role headers for every role in the PRD (§2.1).

ParkManager and FrontDesk are opaque operator credentials — the server never
matches their X-User-ID against a stored entity, so a shared constant is the
canonical form. Member and Guardian are entity-backed: their X-User-ID must equal
the acting entity's id (Member.id, or the signing Participant.id), so ownership-gated
calls MUST use make_member_headers(member_id) / make_guardian_headers(participant_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Member/Guardian ownership (e.g. 401/403/404/422 on missing or bad input).
TEST_USERS = {
    "park_manager_headers": build_user_headers("test-park-manager-1", "ParkManager"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    # Fallback constants — only for non-ownership tests.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_park_manager_headers(user_id: str = "test-park-manager-1") -> dict:
    """ParkManager is opaque; the id is not entity-matched."""
    return build_user_headers(user_id, "ParkManager")


def make_front_desk_headers(user_id: str = "test-front-desk-1") -> dict:
    """FrontDesk is opaque; the id is not entity-matched."""
    return build_user_headers(user_id, "FrontDesk")


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (own membership / reservation /
    pass / party booking actions)."""
    return build_user_headers(user_id, "Member")


def make_guardian_headers(user_id: str) -> dict:
    """For the Guardian role (entity_backed:Participant). Pass the signing
    Participant.id as user_id when e-signing a minor's waiver."""
    return build_user_headers(user_id, "Guardian")
