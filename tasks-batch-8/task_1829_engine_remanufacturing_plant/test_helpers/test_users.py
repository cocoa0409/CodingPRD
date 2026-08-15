"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics: for the Distributor role, X-User-ID is the id of the
acting Distributor entity (entity-backed); for every other role the
X-User-ID is an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Distributor-role tests
# that do not exercise ownership (e.g., malformed-payload rejections).
TEST_USERS = {
    "plant_admin_headers": build_user_headers("admin-1", "PlantAdmin"),
    "core_inspector_headers": build_user_headers("ci-1", "CoreInspector"),
    "shop_technician_headers": build_user_headers("tech-1", "ShopTechnician"),
    "quality_inspector_headers": build_user_headers("qi-1", "QualityInspector"),
    "warranty_adjuster_headers": build_user_headers("adj-1", "WarrantyAdjuster"),
    # Fallback only: ownership-gated calls MUST use make_distributor_headers
    # with the real Distributor.id.
    "distributor_headers": build_user_headers("dist-fallback-1", "Distributor"),
}


def make_distributor_headers(distributor_id: str) -> dict:
    """Distributor is entity-backed: X-User-ID must be the Distributor.id
    whenever the call is ownership-gated (returns, responds, sells, claims)."""
    return build_user_headers(distributor_id, "Distributor")


def make_plant_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_core_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CoreInspector")


def make_shop_technician_headers(user_id: str) -> dict:
    """Opaque identity; choose the user id to control dyno recorded_by and
    claim teardown_by for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "ShopTechnician")


def make_quality_inspector_headers(user_id: str) -> dict:
    """Opaque identity; choose the user id to control sealed_by for
    segregation-of-duties scenarios."""
    return build_user_headers(user_id, "QualityInspector")


def make_warranty_adjuster_headers(user_id: str) -> dict:
    """Opaque identity; choose the user id relative to a claim's teardown_by
    for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "WarrantyAdjuster")
