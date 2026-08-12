"""Pre-built role headers for every role in the PRD (User and Role-Based Access Control)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. For the opaque plant-side roles these are canonical.
# For the entity-backed roles (Grower/Buyer) the shared constant is a fallback
# for non-ownership tests only — ownership-gated calls MUST go through the
# per-instance builders below with the actual entity id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlantAdmin"),
    "intake_headers": build_user_headers("test-intake-1", "IntakeOperator"),
    "lab_headers": build_user_headers("test-lab-1", "LabTechnician"),
    "operator_headers": build_user_headers("test-operator-1", "PlantOperator"),
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlantAdmin is an opaque role; any identifier works."""
    return build_user_headers(user_id, "PlantAdmin")


def make_intake_headers(user_id: str = "test-intake-1") -> dict:
    """IntakeOperator is an opaque role; any identifier works."""
    return build_user_headers(user_id, "IntakeOperator")


def make_lab_headers(user_id: str = "test-lab-1") -> dict:
    """LabTechnician is an opaque role; any identifier works."""
    return build_user_headers(user_id, "LabTechnician")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    """PlantOperator is an opaque role; any identifier works."""
    return build_user_headers(user_id, "PlantOperator")


def make_grower_headers(user_id: str) -> dict:
    """Grower is entity-backed: user_id MUST be the acting Grower's id."""
    return build_user_headers(user_id, "Grower")


def make_buyer_headers(user_id: str) -> dict:
    """Buyer is entity-backed: user_id MUST be the acting Buyer's id."""
    return build_user_headers(user_id, "Buyer")
