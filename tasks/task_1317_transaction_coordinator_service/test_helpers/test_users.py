"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed:Coordinator — fallback ONLY for non-ownership tests (400/404/RBAC)
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    # entity_backed:Agent — fallback ONLY for non-ownership tests (400/404/RBAC)
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    # opaque roles — canonical form
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "title_rep_headers": build_user_headers("test-title-rep-1", "TitleRep"),
    "lender_rep_headers": build_user_headers("test-lender-rep-1", "LenderRep"),
}


# Per-instance builders — required for every entity_backed role.
def make_coordinator_headers(user_id: str) -> dict:
    """For Coordinator (entity_backed:Coordinator). Pass the actual Coordinator.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Coordinator")


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the actual Agent.id as user_id whenever
    the call is ownership-gated (document submit, signature sign/decline)."""
    return build_user_headers(user_id, "Agent")
