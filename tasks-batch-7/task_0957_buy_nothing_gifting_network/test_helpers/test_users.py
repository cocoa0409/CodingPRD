"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are used only by tests whose success does NOT depend on the
caller owning the subject resource (400/404 checks, opaque-role calls).
For ownership-gated calls, use the per-instance builders with the actual
entity id (Member and GroupModerator are entity-backed roles).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form (X-User-ID not compared
    # to any entity id for Anonymous/PlatformAdmin).
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Entity-backed roles: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "moderator_headers": build_user_headers("test-moderator-1", "GroupModerator"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity-backed): pass the actual Member.id whenever the
    call is ownership-gated (post author, claimer, wisher, etc.)."""
    return build_user_headers(user_id, "Member")


def make_moderator_headers(user_id: str) -> dict:
    """For the GroupModerator role (entity-backed): pass the Member.id whose
    APPROVED membership carries role=MODERATOR in the target group."""
    return build_user_headers(user_id, "GroupModerator")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For the PlatformAdmin role (opaque)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers() -> dict:
    """For the Anonymous role (opaque)."""
    return build_user_headers("test-anonymous-1", "Anonymous")
