"""Pre-built role headers for every role in the PRD (§2.1).

WholesaleAdmin, RoutePlanner, WarehouseOps, CreditAdjuster, and TelemetryGateway
are opaque identities: X-User-ID is not tied to any persisted entity.
OperatorManager is entity-backed by Operator (X-User-ID is the acting
operator's id); ownership-gated calls MUST use make_operator_manager_headers
with the real operator id, never the shared fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "wholesale_admin_headers": build_user_headers("test-admin-1", "WholesaleAdmin"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "operator_manager_headers": build_user_headers("test-om-1", "OperatorManager"),
    "route_planner_headers": build_user_headers("test-planner-1", "RoutePlanner"),
    "warehouse_ops_headers": build_user_headers("test-warehouse-1", "WarehouseOps"),
    "credit_adjuster_headers": build_user_headers("test-adjuster-1", "CreditAdjuster"),
    "telemetry_gateway_headers": build_user_headers("test-telemetry-1", "TelemetryGateway"),
}


def make_wholesale_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "WholesaleAdmin")


def make_operator_manager_headers(operator_id: str) -> dict:
    """For OperatorManager (entity_backed:Operator). Pass the acting
    Operator.id whenever the call is ownership-gated."""
    return build_user_headers(operator_id, "OperatorManager")


def make_route_planner_headers(user_id: str = "test-planner-1") -> dict:
    return build_user_headers(user_id, "RoutePlanner")


def make_warehouse_ops_headers(user_id: str = "test-warehouse-1") -> dict:
    return build_user_headers(user_id, "WarehouseOps")


def make_credit_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    return build_user_headers(user_id, "CreditAdjuster")


def make_telemetry_gateway_headers(user_id: str = "test-telemetry-1") -> dict:
    return build_user_headers(user_id, "TelemetryGateway")
