"""Pre-built role headers for every role in the PRD (§2.1).

Anonymous and ParkAdmin are opaque identities: X-User-ID is not tied to any
persisted entity. Member and Steward are entity-backed by Member (X-User-ID is
the acting Member's id); ownership-gated or steward-gated calls MUST use the
per-instance builders with the real Member.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "park_admin_headers": build_user_headers("test-park-admin-1", "ParkAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only — never use these where the call is ownership-gated.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "steward_headers": build_user_headers("test-steward-1", "Steward"),
}


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_park_admin_headers(user_id: str = "test-park-admin-1") -> dict:
    return build_user_headers(user_id, "ParkAdmin")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id whenever
    the call is ownership-gated."""
    return build_user_headers(member_id, "Member")


def make_steward_headers(member_id: str) -> dict:
    """For Steward (entity_backed:Member whose is_steward flag is true). Pass
    the acting Member.id — the member must already carry is_steward == true."""
    return build_user_headers(member_id, "Steward")
