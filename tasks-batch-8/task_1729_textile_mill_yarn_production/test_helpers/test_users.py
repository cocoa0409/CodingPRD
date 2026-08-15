"""Pre-built role headers for every role in the PRD.

All six roles use opaque operator identity (PRD §2.1): X-User-ID is not tied
to any persisted entity, so the shared constants below are canonical for
every call, including ownership-free workflow endpoints.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "mill_planner_headers": build_user_headers("test-planner-1", "MillPlanner"),
    "spinning_supervisor_headers": build_user_headers(
        "test-supervisor-1", "SpinningSupervisor"
    ),
    "dye_house_operator_headers": build_user_headers(
        "test-operator-1", "DyeHouseOperator"
    ),
    "quality_inspector_headers": build_user_headers(
        "test-inspector-1", "QualityInspector"
    ),
    "customer_service_rep_headers": build_user_headers(
        "test-rep-1", "CustomerServiceRep"
    ),
    "mill_admin_headers": build_user_headers("test-admin-1", "MillAdmin"),
}


def make_mill_planner_headers(user_id: str = "test-planner-1") -> dict:
    return build_user_headers(user_id, "MillPlanner")


def make_spinning_supervisor_headers(user_id: str = "test-supervisor-1") -> dict:
    return build_user_headers(user_id, "SpinningSupervisor")


def make_dye_house_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "DyeHouseOperator")


def make_quality_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_customer_service_rep_headers(user_id: str = "test-rep-1") -> dict:
    return build_user_headers(user_id, "CustomerServiceRep")


def make_mill_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "MillAdmin")
