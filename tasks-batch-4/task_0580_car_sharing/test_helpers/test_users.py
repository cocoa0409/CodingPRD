"""Pre-built role headers for every role in the Car Sharing PRD §2.1.

Anonymous and PlatformAdmin are opaque identities (the server never compares
X-User-ID to any entity id), so their shared constants are canonical. Host and
Guest are entity_backed: their X-User-ID must equal the acting entity's id for
ownership-gated calls, so use make_host_headers(host_id) / make_guest_headers(
guest_id) with the real id — never the shared fallback on an ownership path.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque identities — shared constant is the canonical form.
    "anonymous_headers": build_user_headers("anon-signup-1", "Anonymous"),
    "admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # entity_backed fallbacks — safe ONLY for non-ownership tests (e.g. 403/404).
    "host_headers": build_user_headers("test-host-fallback", "Host"),
    "guest_headers": build_user_headers("test-guest-fallback", "Guest"),
}


def make_host_headers(host_id: str) -> dict:
    """Headers for a Host (entity_backed:Host). Pass the real Host.id whenever
    the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(host_id, "Host")


def make_guest_headers(guest_id: str) -> dict:
    """Headers for a Guest (entity_backed:Guest). Pass the real Guest.id whenever
    the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(guest_id, "Guest")


def make_admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def make_anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
