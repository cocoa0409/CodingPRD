"""Pre-built role headers for every role in the PRD.

All nine roles are opaque identities (PRD §2.1): X-User-ID is an opaque
operator identifier, never compared to any resource's id. It is still recorded
— segregation-of-duties checks compare the acting user's X-User-ID against the
creator's X-User-ID — so callers who must distinguish users pass explicit
user ids through the builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    PE_CREATOR_USER_ID,
    QE_DISPOSITIONER_USER_ID,
    QE_REVIEWER_USER_ID,
)

TEST_USERS = {
    "plant_admin_headers": build_user_headers("user-plant-admin", "PlantAdmin"),
    "process_engineer_headers": build_user_headers(PE_CREATOR_USER_ID, "ProcessEngineer"),
    "toolroom_manager_headers": build_user_headers("user-toolroom-manager", "ToolroomManager"),
    "setup_lead_headers": build_user_headers("user-setup-lead", "SetupLead"),
    "production_planner_headers": build_user_headers("user-production-planner", "ProductionPlanner"),
    "press_operator_headers": build_user_headers("user-press-operator", "PressOperator"),
    "quality_engineer_headers": build_user_headers(QE_REVIEWER_USER_ID, "QualityEngineer"),
    "shipping_clerk_headers": build_user_headers("user-shipping-clerk", "ShippingClerk"),
    "cost_analyst_headers": build_user_headers("user-cost-analyst", "CostAnalyst"),
}


def make_plant_admin_headers(user_id: str = "user-plant-admin") -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_process_engineer_headers(user_id: str = PE_CREATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ProcessEngineer")


def make_toolroom_manager_headers(user_id: str = "user-toolroom-manager") -> dict:
    return build_user_headers(user_id, "ToolroomManager")


def make_setup_lead_headers(user_id: str = "user-setup-lead") -> dict:
    return build_user_headers(user_id, "SetupLead")


def make_production_planner_headers(user_id: str = "user-production-planner") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_press_operator_headers(user_id: str = "user-press-operator") -> dict:
    return build_user_headers(user_id, "PressOperator")


def make_quality_engineer_headers(user_id: str = QE_REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "QualityEngineer")


def make_qe_reviewer_headers() -> dict:
    """QualityEngineer identity that begins review / schedules audits."""
    return build_user_headers(QE_REVIEWER_USER_ID, "QualityEngineer")


def make_qe_dispositioner_headers() -> dict:
    """QualityEngineer identity distinct from any creator, for disposition calls."""
    return build_user_headers(QE_DISPOSITIONER_USER_ID, "QualityEngineer")


def make_shipping_clerk_headers(user_id: str = "user-shipping-clerk") -> dict:
    return build_user_headers(user_id, "ShippingClerk")


def make_cost_analyst_headers(user_id: str = "user-cost-analyst") -> dict:
    return build_user_headers(user_id, "CostAnalyst")
