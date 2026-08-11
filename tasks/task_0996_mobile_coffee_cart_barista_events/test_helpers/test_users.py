"""Pre-built role headers for every role in the PRD (§2.1).

OperationsManager is opaque: X-User-ID is recorded but never owner-matched.
Client is entity_backed: X-User-ID must equal the acting Client.id for
ownership-gated calls (booking lifecycle, payments, add-on attach).
Barista is entity_backed: X-User-ID must equal the acting Barista.id for
accept / decline / withdraw.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "ops_manager_headers": build_user_headers("ops-manager-1", "OperationsManager"),
    # entity_backed roles: shared constants are fallbacks for NON-ownership
    # probes only (e.g., a 404/403 probe). Ownership-gated calls MUST use the
    # per-instance builders below with the real entity id.
    "client_headers": build_user_headers("client-user-1", "Client"),
    "barista_headers": build_user_headers("barista-user-1", "Barista"),
}


def make_ops_manager_headers(user_id: str = "ops-manager-1") -> dict:
    """OperationsManager is opaque; the id is never matched against an entity."""
    return build_user_headers(user_id, "OperationsManager")


def make_client_headers(user_id: str) -> dict:
    """Client is entity_backed: pass the actual Client.id as user_id whenever
    the call is ownership-gated (bookings, payments, add-on attach)."""
    return build_user_headers(user_id, "Client")


def make_barista_headers(user_id: str) -> dict:
    """Barista is entity_backed: pass the actual Barista.id as user_id whenever
    the call is ownership-gated (accept, decline, withdraw)."""
    return build_user_headers(user_id, "Barista")
