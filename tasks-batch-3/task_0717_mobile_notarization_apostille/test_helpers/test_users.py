"""Pre-built role headers for every role in the PRD.

Three roles (CoordinatorOps, ApostilleClerk, Viewer) are opaque — their X-User-ID
is not tied to any persisted entity, so the shared constants are the canonical form.

The Notary role is entity-backed: ownership checks compare a resource's notary
foreign key to X-User-ID. Any ownership-gated Notary call MUST therefore use
make_notary_headers(notary["id"]) with the real notary id, never the shared
constant (whose id matches no notary).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "CoordinatorOps"),
    "apostille_clerk_headers": build_user_headers("test-clerk-1", "ApostilleClerk"),
    "viewer_headers": build_user_headers("test-viewer-1", "Viewer"),
    # Fallback for non-ownership Notary tests only (e.g. 403/404 paths).
    "notary_headers": build_user_headers("test-notary-1", "Notary"),
}


def make_notary_headers(notary_id: str) -> dict:
    """Headers for the Notary role (entity_backed:Notary).

    Pass the actual Notary.id as notary_id whenever the call is ownership-gated
    (scheduling sessions, recording verifications/journal acts, start/complete,
    loan-package create/scrub) so the server's ownership check resolves.
    """
    return build_user_headers(notary_id, "Notary")
