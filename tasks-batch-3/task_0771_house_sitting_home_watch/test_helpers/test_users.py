"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Coordinator role, and for tests that
# don't exercise Client/Sitter ownership.
TEST_USERS = {
    # Coordinator is an opaque operator identity (X-User-ID not tied to any entity).
    "coordinator_headers": build_user_headers("op-coordinator-1", "Coordinator"),
    # Client / Sitter are entity_backed: these shared constants are fallbacks for
    # non-ownership tests only (e.g. 401/403/404 on unowned or missing resources).
    "client_headers": build_user_headers("test-client-1", "Client"),
    "sitter_headers": build_user_headers("test-sitter-1", "Sitter"),
}


def make_coordinator_headers(user_id="op-coordinator-1"):
    """Coordinator is opaque; user_id is an operator identifier, never an entity id."""
    return build_user_headers(user_id, "Coordinator")


def make_client_headers(user_id):
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (property/booking/invoice)."""
    return build_user_headers(user_id, "Client")


def make_sitter_headers(user_id):
    """For the Sitter role (entity_backed:Sitter). Pass the actual Sitter.id as
    user_id whenever the call is ownership-gated (visit check-in/out, log, incident)."""
    return build_user_headers(user_id, "Sitter")
