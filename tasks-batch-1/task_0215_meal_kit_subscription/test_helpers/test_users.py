"""Pre-built role headers for every role in the Meal Kit Subscription PRD.

Member is entity_backed:Member — its X-User-ID must equal the acting member's id for
ownership-gated operations, so use make_member_headers(member_id) in fixtures/tests that
exercise ownership. The shared TEST_USERS["member_headers"] constant is a fallback only for
tests that do NOT depend on owning the subject resource (e.g., 400-on-bad-header tests).

Anonymous, PlatformOps, and PlatformAdmin are opaque — their X-User-ID is never compared to
any entity id, so the shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # opaque roles: shared constants are canonical.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    "ops_headers": build_user_headers("test-ops-1", "PlatformOps"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as the user id
    whenever the call is ownership-gated (subscription, weekly box, box-recipe slot)."""
    return build_user_headers(member_id, "Member")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_ops_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "PlatformOps")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
