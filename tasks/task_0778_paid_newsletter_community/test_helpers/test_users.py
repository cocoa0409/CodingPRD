"""Pre-built role headers for every role in the PRD.

Identity binding (PRD §2.1):
  - Member is entity_backed: X-User-ID is the Member.id. Ownership-gated calls
    MUST use make_member_headers(member["id"]).
  - Creator is opaque, but X-User-ID is recorded as creator_user_id on the
    publication and drives publication ownership. Use make_creator_headers with a
    stable id (e.g. "creator_1") for a given publication and its children.
  - Moderator, PlatformAdmin, Anonymous are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# per-resource ownership (403/404/422 cases, admin/moderator operations).
TEST_USERS = {
    "creator_headers": build_user_headers("creator_1", "Creator"),
    "creator_2_headers": build_user_headers("creator_2", "Creator"),
    "member_headers": build_user_headers("member_x", "Member"),
    "moderator_headers": build_user_headers("mod_1", "Moderator"),
    "admin_headers": build_user_headers("admin_1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon_1", "Anonymous"),
}


def make_creator_headers(user_id: str) -> dict:
    """Creator headers for a specific opaque operator id (becomes creator_user_id)."""
    return build_user_headers(user_id, "Creator")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (subscribe, change-tier, cancel,
    reactivate, register, comment, read gated content, own reads)."""
    return build_user_headers(user_id, "Member")
