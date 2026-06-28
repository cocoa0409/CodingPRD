"""Pre-built role headers for every role in the Bridal Beauty PRD.

Three roles exist:
- Coordinator: opaque identity; the shared constant is the canonical form.
- Client: opaque identity, but ownership is established by matching X-User-ID to the
  owning event's client_id. Tests therefore pass the event's client_id as the user id
  when the call is ownership-gated (see make_client_headers).
- Artist: entity_backed:Artist — X-User-ID is the acting Artist entity's id. Ownership
  checks compare the resource's artist FK to X-User-ID, so ownership-gated artist calls
  MUST use make_artist_headers(artist["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-1", "Coordinator"),
    "client_headers": build_user_headers("client-1", "Client"),
    # entity_backed Artist: shared constant is a fallback for non-ownership tests only
    # (e.g. 404 / forbidden-role cases). Ownership-gated calls must use make_artist_headers.
    "artist_headers": build_user_headers("artist-fallback-1", "Artist"),
}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    """Coordinator headers. Identity is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "Coordinator")


def make_client_headers(client_id: str) -> dict:
    """Client headers. Client ownership compares X-User-ID to the owning event's client_id,
    so pass the event's client_id whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")


def make_artist_headers(artist_id: str) -> dict:
    """Artist headers (entity_backed:Artist). Pass the acting Artist entity's id as user_id
    whenever the call is ownership-gated (trial complete, assignment start/complete)."""
    return build_user_headers(artist_id, "Artist")
