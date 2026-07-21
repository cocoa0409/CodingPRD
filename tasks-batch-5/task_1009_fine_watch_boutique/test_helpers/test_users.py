"""Pre-built role headers for every role in the PRD (Section 2.1).

Associate is an opaque operator identity not tied to any persisted entity, so
its shared constant is the canonical form. Client is backed by a Customer and
Watchmaker is backed by a Watchmaker entity — ownership checks compare
X-User-ID to the resource's customer_id / watchmaker_id, so ownership-gated
calls MUST use the per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Associate role, and for tests that do
# not exercise ownership (e.g. 404 on a missing resource, 400 on a bad body).
TEST_USERS = {
    "associate_headers": build_user_headers("operator-associate-1", "Associate"),
    # entity_backed fallbacks — only for non-ownership tests.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "watchmaker_headers": build_user_headers("test-watchmaker-1", "Watchmaker"),
}


# Per-instance builders — required for every entity_backed role.
def make_associate_headers(user_id: str = "operator-associate-1") -> dict:
    """For Associate (opaque). Any string identifier works."""
    return build_user_headers(user_id, "Associate")


def make_client_headers(customer_id: str) -> dict:
    """For Client (entity_backed:Customer). Pass the acting Customer.id so that
    ownership checks against a resource's customer_id succeed."""
    return build_user_headers(customer_id, "Client")


def make_watchmaker_headers(watchmaker_id: str) -> dict:
    """For Watchmaker (entity_backed:Watchmaker). Pass the acting Watchmaker.id
    so that ownership checks against a ticket's watchmaker_id succeed."""
    return build_user_headers(watchmaker_id, "Watchmaker")
