"""Pre-built role headers for every role in the PRD.

Two roles are ``entity_backed`` (Client, Stylist): their ownership checks compare
the resource's foreign key to ``X-User-ID``, so ownership-gated calls MUST use the
per-instance builders below with the real entity id. PlatformAdmin and Anonymous are
opaque identities, so their shared constants are always valid.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, Anonymous) and for tests
# that never exercise ownership (e.g. the client/stylist fallbacks are only used where
# the call is not ownership-gated).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "stylist_headers": build_user_headers("test-stylist-1", "Stylist"),
}


def make_admin_headers() -> dict:
    """PlatformAdmin (opaque). X-User-ID is an operator handle, not an entity id."""
    return build_user_headers("test-admin-1", "PlatformAdmin")


def make_anonymous_headers() -> dict:
    """Anonymous (opaque). Only permitted for client self-registration."""
    return build_user_headers("anon-1", "Anonymous")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the real Client.id whenever the call
    is ownership-gated (engagements, sessions, subscriptions, referrals it owns)."""
    return build_user_headers(client_id, "Client")


def make_stylist_headers(stylist_id: str) -> dict:
    """For Stylist (entity_backed:Stylist). Pass the real Stylist.id whenever the call
    is ownership-gated (sessions, items, lookbooks of engagements it owns)."""
    return build_user_headers(stylist_id, "Stylist")
