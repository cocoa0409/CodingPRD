"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles carry an opaque `X-User-ID` that is never compared to any
entity's `id`; the server only records it as `operator_id` on started runs and
as `submitter_id` / `certifier_id` on quality certs for segregation-of-duties
enforcement. Tests that exercise SoD must therefore use distinct user ids for
the run operator, the cert submitter, and the certifier/rejecter.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    USER_DIE_TECH,
    USER_FORGE_OPERATOR_1,
    USER_FURNACE_OPERATOR,
    USER_PLANT_MANAGER,
    USER_QUALITY_ENGINEER_1,
    USER_QUALITY_ENGINEER_2,
    USER_SALES_PLANNER,
    USER_SAW_OPERATOR,
)

TEST_USERS = {
    "plant_manager_headers": build_user_headers(USER_PLANT_MANAGER, "PlantManager"),
    "saw_operator_headers": build_user_headers(USER_SAW_OPERATOR, "SawOperator"),
    "furnace_operator_headers": build_user_headers(USER_FURNACE_OPERATOR, "FurnaceOperator"),
    "forge_operator_headers": build_user_headers(USER_FORGE_OPERATOR_1, "ForgeOperator"),
    "die_tech_headers": build_user_headers(USER_DIE_TECH, "DieShopTechnician"),
    "quality_engineer_headers": build_user_headers(USER_QUALITY_ENGINEER_1, "QualityEngineer"),
    "quality_engineer_2_headers": build_user_headers(USER_QUALITY_ENGINEER_2, "QualityEngineer"),
    "sales_planner_headers": build_user_headers(USER_SALES_PLANNER, "SalesPlanner"),
}


def make_forge_operator_headers(user_id: str) -> dict:
    """ForgeOperator headers with a specific user id (run operator_id anchor)."""
    return build_user_headers(user_id, "ForgeOperator")


def make_quality_engineer_headers(user_id: str) -> dict:
    """QualityEngineer headers with a specific user id (cert SoD anchor)."""
    return build_user_headers(user_id, "QualityEngineer")
