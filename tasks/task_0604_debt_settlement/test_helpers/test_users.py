"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin and NegotiationAgent carry an opaque identity (X-User-ID not tied
to any entity), so their shared constants are the canonical form. Client is
entity-backed: ownership checks compare Program.client_id to X-User-ID, so any
ownership-gated Client call MUST use make_client_headers(client_id) with the
real Client.id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "negotiation_agent_headers": build_user_headers("test-agent-1", "NegotiationAgent"),
    # Fallback for non-ownership Client tests only (e.g. 403/404 by an arbitrary client).
    "client_headers": build_user_headers("test-client-1", "Client"),
    # Unknown role token for ERR_UNAUTHENTICATED tests.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_client_headers(client_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (deposit, drop, owned reads)."""
    return build_user_headers(client_id, "Client")
