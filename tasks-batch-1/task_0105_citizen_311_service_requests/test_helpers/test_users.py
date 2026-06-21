"""Pre-built role headers for every role in the PRD.

SystemAdmin, Dispatcher and Anonymous identities are opaque operator identifiers
not tied to any persisted entity, so the shared constants are the canonical form.

Agent and Citizen are entity-backed: their X-User-ID must equal a real entity id
for ownership / department checks to pass. Use the make_*_headers builders with the
actual entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — shared constant is the canonical form
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity-backed roles — shared constant is a fallback for non-ownership tests only
    "agent_headers": build_user_headers("agent-shared-1", "Agent"),
    "citizen_headers": build_user_headers("citizen-shared-1", "Citizen"),
}


def make_citizen_headers(user_id: str) -> dict:
    """For Citizen (entity_backed:Citizen). Pass the actual Citizen.id as user_id
    whenever the call is ownership-gated (reopen, survey respond, own-request reads)."""
    return build_user_headers(user_id, "Citizen")


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the actual Agent.id as user_id whenever
    the call is department/assignment-gated (work-order start/complete, TIER1 resolve)."""
    return build_user_headers(user_id, "Agent")


def make_system_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")
