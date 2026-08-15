"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "broker_admin_headers": build_user_headers("ba-1", "BrokerAdmin"),
    "office_manager_headers": build_user_headers("om-1", "OfficeManager"),
    "transaction_coordinator_headers": build_user_headers("tc-1", "TransactionCoordinator"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "agent_headers": build_user_headers("agent-placeholder-1", "Agent"),
}


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the actual Agent.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Agent")


def make_broker_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BrokerAdmin")


def make_office_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OfficeManager")


def make_transaction_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransactionCoordinator")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
