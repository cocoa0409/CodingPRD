"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for tests whose success does NOT depend on the caller
# owning the subject resource (role-deny checks, 400/404 probes, manager-only
# configuration calls). Ownership-gated calls must use the per-instance
# builders below with the real backing entity id.
TEST_USERS = {
    # entity_backed:Agent — fallback for non-ownership calls only.
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    # entity_backed:Agent — fallback for non-ownership calls only.
    "leasing_agent_headers": build_user_headers("test-agent-1", "LeasingAgent"),
    # entity_backed:Application — fallback for non-ownership calls only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_property_manager_headers(user_id: str) -> dict:
    """For PropertyManager (entity_backed:Agent — the manager's agent record).
    Pass the actual Agent.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PropertyManager")


def make_leasing_agent_headers(agent_id: str) -> dict:
    """For LeasingAgent (entity_backed:Agent). Pass the actual Agent.id as
    agent_id whenever the call is ownership-gated (claim/respond/mark-lost)."""
    return build_user_headers(agent_id, "LeasingAgent")


def make_applicant_headers(application_id: str) -> dict:
    """For Applicant (entity_backed:Application). Pass the actual Application.id
    as application_id — lease signing compares X-User-ID to lease.application_id."""
    return build_user_headers(application_id, "Applicant")
