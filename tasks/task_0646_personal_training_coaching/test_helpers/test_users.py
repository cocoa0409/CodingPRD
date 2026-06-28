"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin carries an opaque X-User-ID the server never compares to an entity
id, so its shared constant is the canonical form. Trainer and Client are
entity_backed: their X-User-ID must equal the acting Trainer.id / Client.id, so
ownership-gated calls MUST use the per-instance builders below with the real
entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque PlatformAdmin, plus entity_backed fallbacks used ONLY
# by non-ownership tests (e.g. 401/403/404 where ownership is not exercised).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed fallbacks — NOT for ownership-gated success paths.
    "trainer_headers": build_user_headers("test-trainer-1", "Trainer"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


# ─── Per-instance builders — required for every entity_backed role ───────────

def make_trainer_headers(trainer_id: str) -> dict:
    """For Trainer (entity_backed:Trainer). Pass the real Trainer.id as X-User-ID
    whenever the call is ownership-gated."""
    return build_user_headers(trainer_id, "Trainer")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the real Client.id as X-User-ID
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")
