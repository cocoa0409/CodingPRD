"""Pre-built role headers for every role in the PRD.

Seven roles use opaque operator identifiers; the Volunteer role is
entity-backed: its X-User-ID must equal the acting volunteer record's id,
so ownership-gated calls MUST use make_volunteer_headers(volunteer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manager_headers": build_user_headers("mgr-1", "VRCManager"),
    "intake_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "intake2_headers": build_user_headers("intake-2", "IntakeCoordinator"),
    "vetting_headers": build_user_headers("vet-1", "VettingOfficer"),
    "logistics_headers": build_user_headers("logi-1", "LogisticsCoordinator"),
    "supervisor_headers": build_user_headers("site-1", "SiteSupervisor"),
    "supervisor2_headers": build_user_headers("site-2", "SiteSupervisor"),
    "risk_headers": build_user_headers("risk-1", "RiskOfficer"),
    "agency_headers": build_user_headers("agency-1", "AgencyCoordinator"),
    # Fallback only for Volunteer-role calls that are NOT ownership-gated.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer role is entity-backed: pass the actual Volunteer.id as user_id
    whenever the call is ownership-gated (accept/decline/withdraw/resubmit,
    hour-entry creation, self-registration follow-ups)."""
    return build_user_headers(user_id, "Volunteer")


def make_intake_headers(user_id: str) -> dict:
    """IntakeCoordinator with a specific opaque operator id (SoD scenarios)."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_vetting_headers(user_id: str) -> dict:
    """VettingOfficer with a specific opaque operator id (SoD scenarios)."""
    return build_user_headers(user_id, "VettingOfficer")


def make_supervisor_headers(user_id: str) -> dict:
    """SiteSupervisor with a specific opaque operator id (SoD scenarios)."""
    return build_user_headers(user_id, "SiteSupervisor")


def make_risk_headers(user_id: str) -> dict:
    """RiskOfficer with a specific opaque operator id (SoD scenarios)."""
    return build_user_headers(user_id, "RiskOfficer")
