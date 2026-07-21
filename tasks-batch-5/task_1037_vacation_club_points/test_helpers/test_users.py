"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# ClubAdmin has an opaque identity: X-User-ID is an operator identifier the
# server never compares to any entity id, so the shared constant is the
# canonical form for that role.
#
# Member is entity-backed: X-User-ID must be the acting Member.id. The shared
# constant below is safe ONLY for tests that never reach an ownership comparison
# (e.g. missing-resource 404s, unauthorized-role 403s). Every ownership-gated
# call MUST use make_member_headers(member["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ClubAdmin"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}

# Headers carrying no identity at all — used to prove the authentication gate.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_member_headers(member_id: str) -> dict:
    """Headers for a Member. Pass the acting Member's own id — ownership checks
    compare the resource's owning member field against X-User-ID (PRD §2.1)."""
    return build_user_headers(member_id, "Member")


def make_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """Headers for a ClubAdmin (opaque identity, PRD §2.1)."""
    return build_user_headers(operator_id, "ClubAdmin")
