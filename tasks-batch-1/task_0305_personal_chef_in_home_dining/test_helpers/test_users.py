"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Chef (entity_backed), Client (entity_backed), PlatformAdmin (opaque).

For the two entity_backed roles, ownership checks compare X-User-ID against the
resource's chef_id / client_id (PRD §2.1). Ownership-gated calls MUST therefore
use the per-instance builders below with the real entity id; the shared TEST_USERS
constants are only safe for non-ownership tests (401/403-role/404, or PlatformAdmin
operations whose id is opaque and never compared).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque PlatformAdmin, and for tests that do not
# exercise resource ownership (auth-shape / role-permission / not-found checks).
TEST_USERS = {
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "chef_headers": build_user_headers("test-chef-1", "Chef"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    # opaque role: shared constant is the canonical form (id is never compared).
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_chef_headers(chef_id: str) -> dict:
    """For the Chef role (entity_backed:Chef). Pass the actual Chef.id as X-User-ID
    whenever the call is ownership-gated (confirm / decline / start-prep / complete /
    grocery-run create+finalize / reschedule accept+reject on a chef-owned booking)."""
    return build_user_headers(chef_id, "Chef")


def make_client_headers(client_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    X-User-ID whenever the call is ownership-gated (booking cancel, payments,
    reschedule withdraw, plan generate/pause/resume/cancel)."""
    return build_user_headers(client_id, "Client")


def admin_headers() -> dict:
    """PlatformAdmin headers (opaque identity)."""
    return TEST_USERS["admin_headers"]
