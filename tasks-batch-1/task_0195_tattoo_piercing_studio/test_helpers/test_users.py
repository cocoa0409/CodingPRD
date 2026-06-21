"""Pre-built role headers for every role in the Tattoo & Piercing Studio PRD
(§2.1).

Four roles: StudioManager and Anonymous carry OPAQUE identities whose
X-User-ID is not compared to any persisted entity. Artist and Client are
ENTITY-BACKED: when X-User-Role is Artist, X-User-ID is the acting Artist.id;
when it is Client, X-User-ID is the acting Client.id, and ownership checks
compare the resource's owning foreign key against it.

For any ownership-gated call by an entity-backed role, use the per-instance
builder (make_artist_headers / make_client_headers) with the REAL entity id.
The shared TEST_USERS constants are a fallback only for non-ownership paths
(e.g. 401/403/404/400 checks where the caller does not own the subject).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "manager_headers": build_user_headers("test-manager-1", "StudioManager"),
    # Anonymous self-signup: no auth headers required, but we expose a role
    # marker for the few tests that pass it explicitly.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed shared fallbacks (non-ownership paths only).
    "artist_headers": build_user_headers("test-artist-1", "Artist"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_artist_headers(artist_id: str) -> dict:
    """For the Artist role (entity_backed:Artist). Pass the acting Artist.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(artist_id, "Artist")


def make_client_headers(client_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the acting Client.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """For the StudioManager role (opaque identity)."""
    return build_user_headers(user_id, "StudioManager")


def anonymous_no_auth() -> dict:
    """Headers carrying no auth identity — only Content-Type. Used for the
    Anonymous self-signup surface and for the missing-headers auth tests."""
    return {"Content-Type": "application/json"}


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary role/user-id pair. Used by negative auth
    and cross-role tests."""
    return build_user_headers(user_id, role)
