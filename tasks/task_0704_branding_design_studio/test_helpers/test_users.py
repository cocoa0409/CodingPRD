"""Pre-built role headers for every role in the PRD (§2.1).

StudioOps, Designer, and BillingOps are opaque operator identities: their
X-User-ID is not compared to any persisted entity. The shared constants below
are the canonical form for those roles.

Client is entity-backed: when X-User-Role is Client, X-User-ID must be the id of
the acting Client record. Use make_client_headers(client_id) with the real
Client.id for any ownership-gated call; the shared Client constant is only safe
for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "studio_ops_headers": build_user_headers("test-studioops-1", "StudioOps"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "billing_ops_headers": build_user_headers("test-billingops-1", "BillingOps"),
    # Entity-backed Client — shared constant is a fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_client_headers(client_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (approve/reject/request-revision/
    accept on the client's own project resources)."""
    return build_user_headers(client_id, "Client")
