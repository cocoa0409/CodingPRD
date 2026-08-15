"""Pre-built role headers for every role in the PRD (§2.1).

All roles are opaque: X-User-ID is an operator identifier not tied to any
persisted entity. Shared constants are the canonical form. The per-role
builder functions exist for segregation-of-duties scenarios (PRD §3.2 batch
decide vs creator, §3.7 disposition vs recorder), where two distinct operator
identities of the same role are required.

The shared constants use a "-0" operator id suffix so they can never collide
with the SoD pair identities ("planner-1"/"planner-2", "qi-1"/"qi-2").
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "materials_planner_headers": build_user_headers("test-planner-0", "MaterialsPlanner"),
    "tooling_engineer_headers": build_user_headers("test-tooling-0", "ToolingEngineer"),
    "packaging_engineer_headers": build_user_headers("test-packaging-0", "PackagingEngineer"),
    "plant_manager_headers": build_user_headers("test-manager-0", "PlantManager"),
    "production_scheduler_headers": build_user_headers("test-scheduler-0", "ProductionScheduler"),
    "quality_inspector_headers": build_user_headers("test-inspector-0", "QualityInspector"),
    "any_headers": build_user_headers("test-any-0", "Any"),
}


def make_planner_headers(user_id: str) -> dict:
    """MaterialsPlanner headers for a specific operator id (SoD pairs)."""
    return build_user_headers(user_id, "MaterialsPlanner")


def make_tooling_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ToolingEngineer")


def make_packaging_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PackagingEngineer")


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionScheduler")


def make_inspector_headers(user_id: str) -> dict:
    """QualityInspector headers for a specific operator id (SoD pairs)."""
    return build_user_headers(user_id, "QualityInspector")


__all__ = [
    "TEST_USERS",
    "make_planner_headers",
    "make_tooling_engineer_headers",
    "make_packaging_engineer_headers",
    "make_plant_manager_headers",
    "make_scheduler_headers",
    "make_inspector_headers",
]
