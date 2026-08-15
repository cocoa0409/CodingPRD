"""Pre-built role headers for every role in the PRD.

All nine roles have opaque identity (PRD §2.1): X-User-ID is not tied to any
persisted entity. The shared constants below are safe for every call.

The make_*_headers(user_id) builders exist for tests that need to thread a
specific X-User-ID (e.g., segregation-of-duties checks where submitter and
approver MUST differ, or where the SAME id is required to trigger the check).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical form for opaque roles.
TEST_USERS = {
    "trader_headers": build_user_headers("trader-001", "Trader"),
    "risk_manager_headers": build_user_headers("risk-001", "RiskManager"),
    "logistics_headers": build_user_headers("logistics-001", "LogisticsCoordinator"),
    "warehouse_headers": build_user_headers("wh-001", "WarehouseClerk"),
    "head_roaster_headers": build_user_headers("hr-001", "HeadRoaster"),
    "roast_operator_headers": build_user_headers("ro-001", "RoastOperator"),
    "qa_grader_headers": build_user_headers("qa-001", "QAGrader"),
    "fulfillment_planner_headers": build_user_headers("fp-001", "FulfillmentPlanner"),
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
}


def make_trader_headers(user_id: str = "trader-001") -> dict:
    return build_user_headers(user_id, "Trader")


def make_risk_manager_headers(user_id: str = "risk-001") -> dict:
    return build_user_headers(user_id, "RiskManager")


def make_logistics_headers(user_id: str = "logistics-001") -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_warehouse_headers(user_id: str = "wh-001") -> dict:
    return build_user_headers(user_id, "WarehouseClerk")


def make_head_roaster_headers(user_id: str = "hr-001") -> dict:
    return build_user_headers(user_id, "HeadRoaster")


def make_roast_operator_headers(user_id: str = "ro-001") -> dict:
    return build_user_headers(user_id, "RoastOperator")


def make_qa_grader_headers(user_id: str = "qa-001") -> dict:
    return build_user_headers(user_id, "QAGrader")


def make_fulfillment_planner_headers(user_id: str = "fp-001") -> dict:
    return build_user_headers(user_id, "FulfillmentPlanner")


def make_platform_admin_headers(user_id: str = "admin-001") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
