"""Pre-built role headers for every role in the PRD (§2.1).

Member is entity_backed: ownership-gated calls MUST use make_member_headers(member_id)
with the acting member's real id. PlatformAdmin and Anonymous are opaque identities.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# member ownership (e.g., missing-header auth checks, admin-only operations).
TEST_USERS = {
    # opaque roles: the shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    # entity_backed Member: a fallback ONLY for non-ownership tests.
    "member_headers": build_user_headers("member-generic-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the acting Member's real id
    whenever the call is ownership-gated (requester, host, guest, owner, claimant,
    dispute opener)."""
    return build_user_headers(user_id, "Member")


def make_admin_headers() -> dict:
    """PlatformAdmin (opaque)."""
    return TEST_USERS["admin_headers"]


def make_anonymous_headers() -> dict:
    """Anonymous (opaque); may only self-register."""
    return TEST_USERS["anonymous_headers"]
