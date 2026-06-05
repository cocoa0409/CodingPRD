"""Pre-built role headers for every role in the PRD.

Host and Guest are entity-backed: the X-User-ID must equal the acting entity's
id for ownership checks to pass, so ownership-gated calls MUST use the per-instance
builders make_host_headers(host_id) / make_guest_headers(guest_id). The shared
TEST_USERS constants are only safe for opaque roles or for tests whose success
does not depend on the caller owning the subject resource (401/403/404/422 paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity-backed roles: shared constant is a fallback for non-ownership tests only.
    "host_headers": build_user_headers("test-host-1", "Host"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_host_headers(host_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(host_id, "Host")


def make_guest_headers(guest_id: str) -> dict:
    """For Guest (entity_backed:Guest). Pass the actual Guest.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(guest_id, "Guest")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
