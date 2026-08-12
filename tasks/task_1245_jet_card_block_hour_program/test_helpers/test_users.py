"""Pre-built role headers for every role in the PRD.

Ops and Anonymous are opaque roles: the shared constants are canonical.
Member is entity-backed: ownership-gated calls MUST use make_member_headers()
with the actual Member.id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "ops_headers": build_user_headers("test-ops-1", "Ops"),
    # Opaque role: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed role: fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (trips, refunds, upgrades, disputes)."""
    return build_user_headers(user_id, "Member")
