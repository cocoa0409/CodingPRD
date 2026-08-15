"""Pre-built role headers for every role in the PRD.

PlantManager, LineOperator, QualityTechnician, and RoutePlanner are opaque
identities: X-User-ID is recorded for audit and segregation-of-duties checks
but never compared to an entity id. CoManufacturer is entity-backed by
CoManufacturer (X-User-ID is the acting CoManufacturer entity's id);
ownership-gated calls MUST use make_coman_headers with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "plant_manager_headers": build_user_headers("test-pm-1", "PlantManager"),
    "line_operator_headers": build_user_headers("test-op-1", "LineOperator"),
    "quality_tech_headers": build_user_headers("test-qt-1", "QualityTechnician"),
    "route_planner_headers": build_user_headers("test-rp-1", "RoutePlanner"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "coman_headers": build_user_headers("test-coman-1", "CoManufacturer"),
}


def make_plant_manager_headers(user_id: str = "test-pm-1") -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_line_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LineOperator")


def make_quality_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityTechnician")


def make_route_planner_headers(user_id: str = "test-rp-1") -> dict:
    return build_user_headers(user_id, "RoutePlanner")


def make_coman_headers(co_manufacturer_id: str) -> dict:
    """For CoManufacturer (entity_backed:CoManufacturer). Pass the acting
    CoManufacturer.id whenever the call is ownership-gated."""
    return build_user_headers(co_manufacturer_id, "CoManufacturer")
