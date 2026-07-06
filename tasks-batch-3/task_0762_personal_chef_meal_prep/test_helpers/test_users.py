"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# PlatformAdmin is opaque (X-User-ID is not tied to any entity) — the shared
# constant is the canonical form. The Client/Chef shared entries are fallbacks
# for non-ownership tests only (e.g. role-denial); ownership-gated calls MUST use
# the per-instance builders below with the real entity id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "chef_headers": build_user_headers("test-chef-1", "Chef"),
}


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Client")


def make_chef_headers(user_id: str) -> dict:
    """For Chef (entity_backed:Chef). Pass the actual Chef.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Chef")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]
