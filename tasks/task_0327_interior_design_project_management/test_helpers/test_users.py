"""Pre-built role headers for every role in the PRD.

Three roles (StudioAdmin, Designer, ProcurementCoordinator) are opaque operator
identities — the server never compares X-User-ID to any stored record, so the
shared-constant form is the canonical one for them.

The Client role is entity-backed: X-User-ID must be the id of the acting Client
record, and ownership checks compare a project's client_user_id to X-User-ID.
Any ownership-gated Client call MUST use make_client_headers(client["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The three opaque roles use these everywhere. The Client
# shared constant is a fallback only for non-ownership tests (it will never own
# any real Project, so it must NOT be used for ownership-gated Client calls).
TEST_USERS = {
    "studio_admin_headers": build_user_headers("test-studio-admin-1", "StudioAdmin"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "procurement_coordinator_headers": build_user_headers(
        "test-procurement-coordinator-1", "ProcurementCoordinator"
    ),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


# Per-instance builder — REQUIRED for the entity_backed Client role.
def make_client_headers(client_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (room approve, revision submit,
    punch waive, etc.)."""
    return build_user_headers(client_id, "Client")
