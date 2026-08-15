"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (PlantManager, ProductionOperator, LabAnalyst, QualityManager,
LogisticsCoordinator, BillingClerk) use shared constants: the server records but
never entity-checks their X-User-ID. The Driver role is entity-backed — its
X-User-ID must be an existing Driver id — so Driver headers MUST be built per
instance via make_driver_headers(driver["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_manager_headers": build_user_headers("user-plant-manager-1", "PlantManager"),
    "production_operator_headers": build_user_headers(
        "user-production-operator-1", "ProductionOperator"
    ),
    "lab_analyst_headers": build_user_headers("user-lab-analyst-1", "LabAnalyst"),
    "quality_manager_headers": build_user_headers(
        "user-quality-manager-1", "QualityManager"
    ),
    "logistics_coordinator_headers": build_user_headers(
        "user-logistics-coordinator-1", "LogisticsCoordinator"
    ),
    "billing_clerk_headers": build_user_headers("user-billing-clerk-1", "BillingClerk"),
}


def make_driver_headers(user_id: str) -> dict:
    """For the entity-backed Driver role. Pass an existing Driver.id as user_id;
    any other value fails authentication for every endpoint."""
    return build_user_headers(user_id, "Driver")


def make_operator_headers(user_id: str) -> dict:
    """ProductionOperator headers with a specific identity (segregation tests)."""
    return build_user_headers(user_id, "ProductionOperator")


def make_lab_analyst_headers(user_id: str) -> dict:
    """LabAnalyst headers with a specific identity (segregation tests)."""
    return build_user_headers(user_id, "LabAnalyst")


def make_quality_manager_headers(user_id: str) -> dict:
    """QualityManager headers with a specific identity (segregation tests)."""
    return build_user_headers(user_id, "QualityManager")
