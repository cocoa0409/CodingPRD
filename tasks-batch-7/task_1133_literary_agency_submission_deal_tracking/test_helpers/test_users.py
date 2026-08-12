"""Pre-built role headers for every role in the PRD (section 2.1).

`Agent` is entity-backed: its X-User-ID must be the id of the acting Agent
record, so ownership-gated calls MUST use make_agent_headers(agent["id"]).
The shared `agent_headers` constant is a fallback only for tests that never
exercise agent ownership (e.g. RBAC denials on intake with a fresh agency).

The other three roles use opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared constants.
    "agency_admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "contracts_manager_headers": build_user_headers("cm-1", "ContractsManager"),
    "royalties_accountant_headers": build_user_headers("ra-1", "RoyaltiesAccountant"),
    # Entity-backed role: fallback for non-ownership tests only.
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity-backed by the Agent record). Pass the actual
    Agent.id as user_id whenever the call is ownership- or tenancy-gated."""
    return build_user_headers(user_id, "Agent")


def make_agency_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "AgencyAdmin")


def make_contracts_manager_headers(user_id: str = "cm-1") -> dict:
    return build_user_headers(user_id, "ContractsManager")


def make_royalties_accountant_headers(user_id: str = "ra-1") -> dict:
    return build_user_headers(user_id, "RoyaltiesAccountant")
