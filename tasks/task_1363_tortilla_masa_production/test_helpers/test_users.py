"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles carry an opaque identity: the server never compares X-User-ID
to a persisted entity id. The one place the id is recorded is
ChangeoverRecord.performed_by (stamped from the SanitationTech's X-User-ID at
begin), and segregation of duties compares that recorded value against the
verifier's/failing inspector's X-User-ID — so SoD scenarios must drive those
calls with explicit user ids via the builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

SANITATION_USER_ID = "san-01"
INSPECTOR_USER_ID = "qi-01"

TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm-01", "PlantManager"),
    "miller_operator_headers": build_user_headers("miller-01", "MillerOperator"),
    "quality_inspector_headers": build_user_headers(INSPECTOR_USER_ID, "QualityInspector"),
    "line_scheduler_headers": build_user_headers("sched-01", "LineScheduler"),
    "sanitation_tech_headers": build_user_headers(SANITATION_USER_ID, "SanitationTech"),
    "packaging_lead_headers": build_user_headers("pack-01", "PackagingLead"),
    "route_dispatcher_headers": build_user_headers("disp-01", "RouteDispatcher"),
}


def make_sanitation_tech_headers(user_id: str) -> dict:
    """SanitationTech headers for an explicit operator id (changeover performer)."""
    return build_user_headers(user_id, "SanitationTech")


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector headers for an explicit operator id.

    Passing the changeover performer's user id here reproduces the forbidden
    same-person perform-then-verify path (PRD §3.6).
    """
    return build_user_headers(user_id, "QualityInspector")
