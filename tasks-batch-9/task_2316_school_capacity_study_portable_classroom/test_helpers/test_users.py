"""Acting principals for each role declared by the PRD.

For the seven operator roles `X-User-ID` is an opaque identifier that is never
compared against an entity id.  For `CrewLead`, `X-User-ID` must be the `id` of
the acting `InstallationCrew`, so those headers are built per crew.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "DistrictAdmin": "admin-1",
    "FacilitiesPlanner": "planner-1",
    "CapacityCertifier": "certifier-9",
    "PermitCoordinator": "permits-7",
    "BuildingOfficial": "official-4",
    "OperationsScheduler": "sched-2",
    "AssetManager": "assets-3",
}

# A second author identity, for tests that need an operator identity distinct
# from the one that authored a study.
SECOND_PLANNER_USER_ID = "planner-2"
SECOND_CERTIFIER_USER_ID = "certifier-4"


def headers_for(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for one of the seven opaque operator roles."""
    return build_user_headers(user_id or TEST_USERS[role], role)


def make_crew_lead_headers(crew_id: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for a `CrewLead` acting as the crew whose id is `crew_id`."""
    return build_user_headers(user_id or crew_id, "CrewLead")


ADMIN_HEADERS = headers_for("DistrictAdmin")
PLANNER_HEADERS = headers_for("FacilitiesPlanner")
CERTIFIER_HEADERS = headers_for("CapacityCertifier")
PERMIT_HEADERS = headers_for("PermitCoordinator")
OFFICIAL_HEADERS = headers_for("BuildingOfficial")
SCHEDULER_HEADERS = headers_for("OperationsScheduler")
ASSET_HEADERS = headers_for("AssetManager")

OPERATOR_HEADERS = {
    "DistrictAdmin": ADMIN_HEADERS,
    "FacilitiesPlanner": PLANNER_HEADERS,
    "CapacityCertifier": CERTIFIER_HEADERS,
    "PermitCoordinator": PERMIT_HEADERS,
    "BuildingOfficial": OFFICIAL_HEADERS,
    "OperationsScheduler": SCHEDULER_HEADERS,
    "AssetManager": ASSET_HEADERS,
}
