"""Pre-built role headers for every role in the PRD (section 2.1).

Five roles: Admin, Dispatcher, Client, Server, Notary.

- Admin / Dispatcher / Notary carry an OPAQUE X-User-ID not tied to any entity;
  the shared constant is the canonical form.
- Client / Server are entity_backed: ownership checks compare X-User-ID against
  the entity's own id. For any ownership-gated call, use the per-instance builder
  (make_client_headers(client_id) / make_server_headers(server_id)) with the real
  entity id — the shared constant is only a fallback for non-ownership tests
  (e.g. 404 / 422 / role-denial checks).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "notary_headers": build_user_headers("test-notary-1", "Notary"),
    # Entity-backed fallbacks — only safe where ownership is not exercised.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "server_headers": build_user_headers("test-server-1", "Server"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "Admin")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_notary_headers(user_id: str) -> dict:
    """Notary X-User-ID is opaque but is compared to declarant_server_id for
    the segregation-of-duties check; pass a value distinct from the declarant."""
    return build_user_headers(user_id, "Notary")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Client")


def make_server_headers(user_id: str) -> dict:
    """For Server (entity_backed:Server). Pass the actual Server.id whenever the
    call is ownership-gated (accept, attempts, services, stakeouts, sign...)."""
    return build_user_headers(user_id, "Server")
