"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed: for `QualityInspector` and `LineOperator`,
`X-User-ID` is the `id` of the acting `Operator`. Any ownership-gated call
(pull tests, electrical tests, harness builds, rework completion) MUST use the
per-instance builders below with the real Operator id — the shared constants
for those two roles exist only for tests that never exercise identity stamping
(for example 400/404 rejection paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID is not tied to any persisted entity.
    "harness_engineer_headers": build_user_headers("test-harness-engineer-1", "HarnessEngineer"),
    "process_engineer_headers": build_user_headers("test-process-engineer-1", "ProcessEngineer"),
    "quality_manager_headers": build_user_headers("test-quality-manager-1", "QualityManager"),
    "production_planner_headers": build_user_headers("test-production-planner-1", "ProductionPlanner"),
    "materials_clerk_headers": build_user_headers("test-materials-clerk-1", "MaterialsClerk"),
    "shipping_clerk_headers": build_user_headers("test-shipping-clerk-1", "ShippingClerk"),
    # Entity-backed roles: fallback constants for non-identity tests ONLY.
    "quality_inspector_headers": build_user_headers("test-quality-inspector-1", "QualityInspector"),
    "line_operator_headers": build_user_headers("test-line-operator-1", "LineOperator"),
}


def make_quality_inspector_headers(user_id: str) -> dict:
    """For QualityInspector (entity-backed by Operator). Pass the actual
    Operator.id whenever the call records or stamps an operator identity."""
    return build_user_headers(user_id, "QualityInspector")


def make_line_operator_headers(user_id: str) -> dict:
    """For LineOperator (entity-backed by Operator). Pass the actual
    Operator.id whenever the call stamps `built_by_operator_id` or otherwise
    exercises operator identity."""
    return build_user_headers(user_id, "LineOperator")
