"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. The SewingOperator entry below is a fallback only; ownership-gated
# piece-work logging MUST use make_sewing_operator_headers(operator["id"]).
TEST_USERS = {
    "merchandiser_headers": build_user_headers("u-m1", "Merchandiser"),
    "merchandiser2_headers": build_user_headers("u-m2", "Merchandiser"),
    "materials_planner_headers": build_user_headers("u-mp1", "MaterialsPlanner"),
    "cutting_manager_headers": build_user_headers("u-cm1", "CuttingManager"),
    "production_planner_headers": build_user_headers("u-pp1", "ProductionPlanner"),
    "line_supervisor_headers": build_user_headers("u-ls1", "LineSupervisor"),
    "sewing_operator_headers": build_user_headers("u-op-fallback", "SewingOperator"),
    "quality_inspector_headers": build_user_headers("u-qi1", "QualityInspector"),
    "quality_inspector2_headers": build_user_headers("u-qi2", "QualityInspector"),
    "payroll_clerk_headers": build_user_headers("u-pc1", "PayrollClerk"),
    "payroll_clerk2_headers": build_user_headers("u-pc2", "PayrollClerk"),
    "plant_manager_headers": build_user_headers("u-pm1", "PlantManager"),
    "plant_manager2_headers": build_user_headers("u-pm2", "PlantManager"),
    # Same human id under two different roles — needed by segregation-of-duties
    # tests (reviewer == creator, decider == calculator).
    "pm_as_u_m1_headers": build_user_headers("u-m1", "PlantManager"),
    "pm_as_u_pc1_headers": build_user_headers("u-pc1", "PlantManager"),
    # `Any` is a documentation-only pseudo-role (PRD §2.1); on the wire a read
    # call must present one of the nine declared roles, since reads admit all.
    "any_headers": build_user_headers("u-any1", "PlantManager"),
}


def make_sewing_operator_headers(user_id: str) -> dict:
    """For SewingOperator (entity-backed: Operator). Pass the actual Operator.id
    as user_id whenever the call is ownership-gated (piece-work logging)."""
    return build_user_headers(user_id, "SewingOperator")


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_merchandiser_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Merchandiser")


def make_payroll_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayrollClerk")


def make_quality_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_line_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LineSupervisor")


def make_materials_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaterialsPlanner")


def make_cutting_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CuttingManager")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")
