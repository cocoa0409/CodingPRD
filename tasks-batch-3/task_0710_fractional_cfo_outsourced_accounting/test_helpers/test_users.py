"""Pre-built role headers for every role in the PRD.

CFO, Bookkeeper, and PlatformAdmin carry an opaque X-User-ID that the server
never compares to any entity id, so a shared constant is always correct for
those roles. ClientContact is entity-backed by the Client: its X-User-ID must
equal the acting Client's id on any ownership-gated call, so the per-instance
builder make_client_contact_headers(client_id) is mandatory there.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "cfo_headers": build_user_headers("test-cfo-1", "CFO"),
    "bookkeeper_headers": build_user_headers("test-bookkeeper-1", "Bookkeeper"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # ClientContact shared constant: only safe for tests that do NOT exercise
    # the client_id == X-User-ID ownership check (e.g. 404-on-missing-resource).
    "client_contact_headers": build_user_headers("test-client-contact-1", "ClientContact"),
}


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact (entity_backed:Client). Pass the acting Client's id as
    user_id whenever the call is ownership-gated (dispute, reject/approve catch-up,
    pay retainer invoice)."""
    return build_user_headers(client_id, "ClientContact")
