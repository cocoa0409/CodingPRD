"""Pre-built role headers for every role in the PRD (§2.1).

PlantManager and Inspector are opaque roles: X-User-ID is not compared to any
persisted entity id. Operator is entity-backed: X-User-ID must be the acting
Operator entity's id, so ownership-gated calls MUST use make_operator_headers()
with the real Operator.id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "plant_manager_headers": build_user_headers("test-plant-manager-1", "PlantManager"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # Entity-backed role — shared constant is a fallback for non-ownership tests only.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
}

# Headers with no authentication material at all (for ERR_UNAUTHENTICATED tests).
ANON_HEADERS = {"Content-Type": "application/json"}

# Role header present but X-User-ID absent (also ERR_UNAUTHENTICATED per PRD §2.1).
ROLE_ONLY_HEADERS = {"X-User-Role": "PlantManager", "Content-Type": "application/json"}


def make_operator_headers(operator_id: str) -> dict:
    """For Operator (entity-backed). Pass the actual Operator.id whenever the
    call is ownership-gated (log recording/verification, incident actions)."""
    return build_user_headers(operator_id, "Operator")


def make_plant_manager_headers(user_id: str = "test-plant-manager-1") -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")
