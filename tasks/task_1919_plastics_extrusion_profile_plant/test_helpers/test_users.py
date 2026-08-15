"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers: X-User-ID is never compared
against any entity id. Segregation-of-duties workflows anchor on the raw
X-User-ID value, so dedicated inspector ids are provided via
make_quality_inspector_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm-1", "PlantManager"),
    "process_engineer_headers": build_user_headers("pe-1", "ProcessEngineer"),
    "line_operator_headers": build_user_headers("lo-1", "LineOperator"),
    "quality_inspector_headers": build_user_headers("qi-1", "QualityInspector"),
    "sales_engineer_headers": build_user_headers("se-1", "SalesEngineer"),
}


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector headers with an explicit X-User-ID.

    Required for segregation-of-duties flows (PRD §3.3 batch RE_RELEASE and
    §3.6 manual-hold RELEASE), where the releasing inspector's X-User-ID must
    differ from the id stamped on the prior action.
    """
    return build_user_headers(user_id, "QualityInspector")
