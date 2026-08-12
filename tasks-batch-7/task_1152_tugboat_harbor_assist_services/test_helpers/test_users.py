"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "port_admin_headers": build_user_headers("test-port-admin-1", "PortAdmin"),
    "port_dispatcher_headers": build_user_headers("test-port-dispatcher-1", "PortDispatcher"),
    "marine_surveyor_headers": build_user_headers("test-marine-surveyor-1", "MarineSurveyor"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests only.
    "vessel_agent_headers": build_user_headers("test-vessel-agent-1", "VesselAgent"),
    "pilot_headers": build_user_headers("test-pilot-1", "Pilot"),
    "tug_captain_headers": build_user_headers("test-tug-captain-1", "TugCaptain"),
}


# Per-instance builders — required for every entity_backed role when the call is
# ownership-gated (pass the actual entity's id as user_id).
def make_vessel_agent_headers(vessel_id: str) -> dict:
    """For VesselAgent (entity_backed:Vessel). Pass the actual Vessel.id whenever the
    call is ownership-gated (job-order create/amend/cancel, damage-claim create)."""
    return build_user_headers(vessel_id, "VesselAgent")


def make_pilot_headers(pilot_id: str) -> dict:
    """For Pilot (entity_backed:Pilot). Pass the actual Pilot.id whenever the call is
    ownership-gated (booking confirm/board)."""
    return build_user_headers(pilot_id, "Pilot")


def make_tug_captain_headers(tug_id: str) -> dict:
    """For TugCaptain (entity_backed:Tug). Pass the actual Tug.id whenever the call is
    ownership-gated (assignment confirm, watch-rotation create, incident create)."""
    return build_user_headers(tug_id, "TugCaptain")
