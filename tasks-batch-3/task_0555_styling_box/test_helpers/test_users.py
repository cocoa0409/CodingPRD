"""Pre-built role headers for every role in the PRD.

The four roles are Anonymous, Client, Stylist, OpsAdmin (PRD §2.1). Client and
Stylist are entity-backed: ownership checks compare X-User-ID to a persisted
entity id, so ownership-gated calls MUST use the per-instance builders below with
the real entity id. Anonymous carries no auth headers; OpsAdmin is opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (OpsAdmin) and for tests that do not
# exercise ownership (e.g. 401/404 checks). Anonymous sends no auth headers.
TEST_USERS = {
    "ops_headers": build_user_headers("ops-admin-1", "OpsAdmin"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "stylist_headers": build_user_headers("test-stylist-1", "Stylist"),
    "anonymous_headers": {},
}


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Client")


def make_stylist_headers(user_id: str) -> dict:
    """For Stylist (entity_backed:Stylist). Pass the acting Stylist.id as user_id
    whenever the call is ownership-gated (curating an assigned fix)."""
    return build_user_headers(user_id, "Stylist")
