"""Pre-built role headers for every role in the PRD.

All five roles have opaque identity (PRD §2.1): `X-User-ID` is never compared
to any entity's `id`, so the shared constants below are the canonical form.
The per-user builders exist for the segregation-of-duties workflow, where the
comparison is between two recorded operator identifiers (swab recorder vs
releasing QA reviewer) and tests must control the user id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "production_planner_headers": build_user_headers("planner-1", "ProductionPlanner"),
    "plant_manager_headers": build_user_headers("pm-1", "PlantManager"),
    "line_operator_headers": build_user_headers("op-1", "LineOperator"),
    "sanitation_lead_headers": build_user_headers("san-1", "SanitationLead"),
    "quality_manager_headers": build_user_headers("qm-1", "QualityManager"),
}


def make_production_planner_headers(user_id: str) -> dict:
    """ProductionPlanner headers for a specific operator id."""
    return build_user_headers(user_id, "ProductionPlanner")


def make_plant_manager_headers(user_id: str) -> dict:
    """PlantManager headers for a specific operator id."""
    return build_user_headers(user_id, "PlantManager")


def make_line_operator_headers(user_id: str) -> dict:
    """LineOperator headers for a specific operator id."""
    return build_user_headers(user_id, "LineOperator")


def make_sanitation_lead_headers(user_id: str) -> dict:
    """SanitationLead headers for a specific operator id (swab recorder)."""
    return build_user_headers(user_id, "SanitationLead")


def make_quality_manager_headers(user_id: str) -> dict:
    """QualityManager headers for a specific operator id (QA releaser)."""
    return build_user_headers(user_id, "QualityManager")
