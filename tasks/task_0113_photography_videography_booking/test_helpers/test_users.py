"""Pre-built role headers for every role in the PRD (PRD §2.1).

Four roles: Anonymous and StudioAdmin are opaque (X-User-ID is an operator id not
tied to any entity), so their shared-constant form is canonical. Client and
Photographer are entity-backed: ownership checks compare X-User-ID to the resource's
owning foreign key (Client.client_id on the booking; Photographer.lead_photographer_id
on the booking). For any ownership-gated call the per-instance builders
make_client_headers(client_id) / make_photographer_headers(photographer_id) MUST be
used with the real entity id — the shared constants are only safe for tests that do
not exercise ownership (e.g. 401/403/404 on unowned resources, or StudioAdmin calls).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque operator — canonical form
    "admin_headers": build_user_headers("studio-admin-1", "StudioAdmin"),
    # entity-backed fallbacks: ONLY for non-ownership tests.
    "client_headers": build_user_headers("client-fallback-1", "Client"),
    "photographer_headers": build_user_headers("photographer-fallback-1", "Photographer"),
}

# Anonymous: no X-User-ID binds to an entity; permitted only to self-register.
ANONYMOUS_HEADERS = {"X-User-Role": "Anonymous", "X-User-ID": "anon-1", "Content-Type": "application/json"}

# No-auth headers (omit X-User-ID and X-User-Role) for ERR_UNAUTHENTICATED tests.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_admin_headers(user_id: str = "studio-admin-1") -> dict:
    """StudioAdmin headers (opaque operator)."""
    return build_user_headers(user_id, "StudioAdmin")


def make_client_headers(user_id: str) -> dict:
    """Client headers (entity_backed:Client). Pass the actual Client.id whenever the
    call is ownership-gated (confirm/cancel/sign/request-revision/proof-selection/
    add-on-order on an owned booking)."""
    return build_user_headers(user_id, "Client")


def make_photographer_headers(user_id: str) -> dict:
    """Photographer headers (entity_backed:Photographer). Pass the actual Photographer.id
    (the lead photographer on the booking) whenever the call is ownership-gated
    (shoot complete / gallery upload / gallery finalize)."""
    return build_user_headers(user_id, "Photographer")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Anonymous headers (opaque; self-registration only)."""
    return build_user_headers(user_id, "Anonymous")
