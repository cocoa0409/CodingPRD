"""Pre-built role headers for every role in the PRD (§2.1).

The Customer role is entity-backed: X-User-ID must be the acting Customer
record's id, so ownership-gated calls MUST use make_customer_headers(customer_id).
The other six roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # Opaque roles: shared constants are the canonical form.
    "sales_engineer_headers": build_user_headers("test-sales-1", "SalesEngineer"),
    "cam_operator_headers": build_user_headers("test-cam-1", "CAMOperator"),
    "process_engineer_headers": build_user_headers("test-eng-1", "ProcessEngineer"),
    "quality_inspector_headers": build_user_headers("test-qi-1", "QualityInspector"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "fab_admin_headers": build_user_headers("test-admin-1", "FabAdmin"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id whenever the call
    is ownership-gated (order create/read, invoice pay, cancel as owner)."""
    return build_user_headers(customer_id, "Customer")


def make_sales_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesEngineer")


def make_cam_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CAMOperator")


def make_process_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcessEngineer")


def make_quality_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_fab_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FabAdmin")
