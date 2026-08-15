"""Pre-built role headers for every role in the PRD.

All four roles are opaque identities: the PRD states that `X-User-ID` is an
opaque operator identifier not tied to any persisted entity, and that
segregation-of-duties checks compare one operator's identifier string against
another's. The literal ids below (ic_1, ta_1, tl_1, ...) are pinned so tests
can control SoD comparisons deliberately.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("ic_1", "IntakeCoordinator"),
    "threat_assessor_headers": build_user_headers("ta_1", "ThreatAssessor"),
    "team_lead_headers": build_user_headers("tl_1", "TeamLead"),
    "district_admin_headers": build_user_headers("da_1", "DistrictAdministrator"),
}


def make_intake_coordinator_headers(user_id: str = "ic_1") -> dict:
    """IntakeCoordinator headers carrying the given operator id."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_threat_assessor_headers(user_id: str = "ta_1") -> dict:
    """ThreatAssessor headers carrying the given operator id."""
    return build_user_headers(user_id, "ThreatAssessor")


def make_team_lead_headers(user_id: str = "tl_1") -> dict:
    """TeamLead headers carrying the given operator id."""
    return build_user_headers(user_id, "TeamLead")


def make_district_admin_headers(user_id: str = "da_1") -> dict:
    """DistrictAdministrator headers carrying the given operator id."""
    return build_user_headers(user_id, "DistrictAdministrator")
