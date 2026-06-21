"""Pre-built role headers for every role in the PRD (§2.1).

Roles:
  - StudioManager : opaque operator id (never compared to any entity id).
  - Client        : entity_backed:Client  — X-User-ID must be the acting Client.id
                    for ownership-gated calls.
  - Engineer      : entity_backed:Engineer — X-User-ID must be the acting Engineer.id
                    for ownership-gated delivery calls.
  - Anonymous     : opaque id; may only self-register a client or bootstrap a studio.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (StudioManager, Anonymous), and for any
# test whose success does NOT depend on the caller owning the subject resource.
TEST_USERS = {
    "studio_manager_headers": build_user_headers("test-manager-1", "StudioManager"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed fallbacks — only valid for non-ownership tests (e.g. 404/403 probes).
    "client_headers": build_user_headers("test-client-1", "Client"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
}


def make_studio_manager_headers(user_id: str = "test-manager-1") -> dict:
    """StudioManager is opaque; any id works."""
    return build_user_headers(user_id, "StudioManager")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous is opaque; any id works."""
    return build_user_headers(user_id, "Anonymous")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client.id as user_id
    whenever the call is ownership-gated (own bookings, payments, deliveries)."""
    return build_user_headers(user_id, "Client")


def make_engineer_headers(user_id: str) -> dict:
    """For Engineer (entity_backed:Engineer). Pass the acting Engineer.id as user_id
    whenever the call is ownership-gated (delivering on an assigned booking)."""
    return build_user_headers(user_id, "Engineer")
