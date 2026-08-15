"""Pre-built role headers for every role in the PRD.

Anonymous and CoopAdmin carry opaque identifiers never compared to any entity id.
The Member role is entity-backed: for ownership-gated calls, build headers with
the acting member's real id via make_member_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for Member calls that are not
# ownership-gated (e.g., 400-on-bad-payload probes).
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "admin_headers": build_user_headers("test-admin-1", "CoopAdmin"),
    # Fallback only for non-ownership Member calls; prefer make_member_headers().
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_anonymous_headers(user_id: str) -> dict:
    """Anonymous role with an explicit opaque identifier."""
    return build_user_headers(user_id, "Anonymous")


def make_admin_headers(user_id: str) -> dict:
    """CoopAdmin role with an explicit opaque operator identifier."""
    return build_user_headers(user_id, "CoopAdmin")


def make_member_headers(user_id: str) -> dict:
    """Member role is entity-backed: pass the acting Member.id as user_id
    whenever the call is ownership-gated (owner, claimer, sitter, referee,
    mediator identity checks compare the foreign key to X-User-ID)."""
    return build_user_headers(user_id, "Member")
