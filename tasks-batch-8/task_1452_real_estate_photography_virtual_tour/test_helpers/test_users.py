"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for the opaque roles (Coordinator, OpsAdmin) and for
tests that never exercise an ownership check. For the entity-backed roles
(ClientAgent, Photographer) ALWAYS prefer the per-instance builders when the
downstream call is ownership-gated: X-User-ID must equal the entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed roles: fallback for non-ownership tests only
    "client_agent_headers": build_user_headers("test-agent-1", "ClientAgent"),
    "photographer_headers": build_user_headers("test-photographer-1", "Photographer"),
    # opaque roles: canonical form
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "ops_admin_headers": build_user_headers("test-opsadmin-1", "OpsAdmin"),
}


def make_client_agent_headers(user_id: str) -> dict:
    """ClientAgent is entity-backed: pass the actual ClientAgent.id whenever the
    call is ownership-gated (submit/cancel/patch/reschedule/addons/revisions/accept)."""
    return build_user_headers(user_id, "ClientAgent")


def make_photographer_headers(user_id: str) -> dict:
    """Photographer is entity-backed: pass the actual Photographer.id whenever the
    call is assignment-gated (mark-shot/deliver/claim)."""
    return build_user_headers(user_id, "Photographer")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "Coordinator")


def make_ops_admin_headers(user_id: str = "test-opsadmin-1") -> dict:
    return build_user_headers(user_id, "OpsAdmin")
