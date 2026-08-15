"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (OpsAdmin, Dispatcher, BookingAgent,
# ComplianceOfficer, CommunityReporter): their X-User-ID is not compared to any
# entity id except where the PRD records it (flight created_by / dispatched_by).
TEST_USERS = {
    "ops_admin_headers": build_user_headers("ops-1", "OpsAdmin"),
    # Two distinct dispatchers so segregation-of-duties scenarios can pick
    # creator (disp-1) vs dispatcher (disp-2).
    "dispatcher_headers": build_user_headers("disp-1", "Dispatcher"),
    "dispatcher_2_headers": build_user_headers("disp-2", "Dispatcher"),
    "booking_agent_headers": build_user_headers("agent-1", "BookingAgent"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "community_reporter_headers": build_user_headers("reporter-1", "CommunityReporter"),
    # Fallback for non-ownership Pilot calls only. Pilot is entity-backed:
    # ownership-gated calls MUST use make_pilot_headers(pilot_id) instead.
    "pilot_headers": build_user_headers("test-pilot-1", "Pilot"),
}


def make_pilot_headers(pilot_id: str) -> dict:
    """For Pilot (entity-backed: Pilot). Pass the actual Pilot.id as pilot_id
    whenever the call is ownership-gated (PILOT_ACK, duty-day self-reads)."""
    return build_user_headers(pilot_id, "Pilot")


def make_dispatcher_headers(user_id: str) -> dict:
    """Dispatcher is opaque; distinct user ids matter for segregation of duties."""
    return build_user_headers(user_id, "Dispatcher")
