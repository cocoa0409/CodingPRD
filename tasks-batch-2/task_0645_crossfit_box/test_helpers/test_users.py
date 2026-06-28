"""Pre-built role headers for every role in the PRD.

BoxManager and Anonymous are opaque roles (X-User-ID not tied to an entity).
Coach and Member are entity_backed: ownership checks compare X-User-ID to the
acting entity's id, so ownership-gated calls MUST use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (e.g. 404-on-missing-resource, 422-on-bad-payload, RBAC role checks).
TEST_USERS = {
    "box_manager_headers": build_user_headers("test-box-manager-1", "BoxManager"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed fallbacks — only for non-ownership tests.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
}


# Per-instance builders — required for every entity_backed role.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_coach_headers(user_id: str) -> dict:
    """For Coach (entity_backed:Coach). Pass the actual Coach.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Coach")


def make_box_manager_headers(user_id: str = "test-box-manager-1") -> dict:
    """BoxManager is opaque; user_id is an operator identifier, not an entity id."""
    return build_user_headers(user_id, "BoxManager")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous is opaque; user_id is a visitor identifier, not an entity id."""
    return build_user_headers(user_id, "Anonymous")
