"""Pre-built role headers for every role in the PRD (§2.1).

Pilot is entity-backed: ownership-gated calls (start/board/complete, incident
report) MUST use make_pilot_headers(pilot_id) with the actual Pilot.id.
VesselAgent is opaque but ownership-keyed on the order's agent_id, so tests
that manage one order share one agent id via make_agent_headers(agent_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "AssociationAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    # Fallback for non-ownership tests (e.g., RBAC rejection checks).
    "pilot_headers": build_user_headers("test-pilot-1", "Pilot"),
    # Canonical vessel agent id for tests that create and then amend/cancel.
    "vessel_agent_headers": build_user_headers("agent-1", "VesselAgent"),
}


def make_pilot_headers(user_id: str) -> dict:
    """For Pilot (entity_backed:Pilot). Pass the actual Pilot.id as user_id
    whenever the call is ownership-gated (start/board/complete/incident)."""
    return build_user_headers(user_id, "Pilot")


def make_agent_headers(agent_id: str) -> dict:
    """VesselAgent is opaque, but order ownership compares X-User-ID to the
    order's captured agent_id — reuse the same id for amend/cancel."""
    return build_user_headers(agent_id, "VesselAgent")
