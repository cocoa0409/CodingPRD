"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For CustomerQualityRep (entity-backed by Customer) these are a
# fallback for non-ownership tests only.
TEST_USERS = {
    "plant_admin": build_user_headers("test-admin-1", "PlantAdmin"),
    "process_engineer": build_user_headers("test-engineer-1", "ProcessEngineer"),
    "quality_technician": build_user_headers("qt-1", "QualityTechnician"),
    "production_scheduler": build_user_headers("test-scheduler-1", "ProductionScheduler"),
    "logistics_coordinator": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    # entity_backed: fallback only; ownership-gated calls must use the builder.
    "customer_quality_rep": build_user_headers("test-rep-1", "CustomerQualityRep"),
}


def make_customer_quality_rep_headers(customer_id: str) -> dict:
    """CustomerQualityRep is entity-backed: X-User-ID must be the Customer.id
    for ownership-gated calls (qualification review, customer sub-resources)."""
    return build_user_headers(customer_id, "CustomerQualityRep")


def make_quality_technician_headers(user_id: str) -> dict:
    """Opaque role, but segregation-of-duties rules compare X-User-ID values
    on quality lots, so tests sometimes need distinct technician identities."""
    return build_user_headers(user_id, "QualityTechnician")


def make_process_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcessEngineer")


def make_production_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionScheduler")
