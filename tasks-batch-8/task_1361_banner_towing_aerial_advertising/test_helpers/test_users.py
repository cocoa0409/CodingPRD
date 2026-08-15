"""Pre-built role headers for every role in the PRD (§2.1).

Client and Pilot are entity-backed roles: their X-User-ID must be the id of
an existing Client / Pilot respectively. Fixtures and tests that perform
ownership-gated calls MUST use the per-instance builders below with the real
entity id. The shared constants for those two roles are placeholders for
non-ownership tests only. The other five roles are opaque: X-User-ID is an
operator identifier never compared to any entity id, so the shared constants
are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "client_headers": build_user_headers("test-client-placeholder", "Client"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "pilot_headers": build_user_headers("test-pilot-placeholder", "Pilot"),
    "ground_crew_lead_headers": build_user_headers("test-ground-crew-1", "GroundCrewLead"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
}


def make_client_headers(user_id: str) -> dict:
    """Client is entity_backed by Client: pass the real Client.id whenever
    the call is ownership-gated (booking, cancelling, approving revisions)."""
    return build_user_headers(user_id, "Client")


def make_pilot_headers(user_id: str) -> dict:
    """Pilot is entity_backed by Pilot: pass the real Pilot.id whenever the
    call is ownership-gated (filing a FlightLog, submitting ProofOfFlight)."""
    return build_user_headers(user_id, "Pilot")
