"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles (X-User-ID never compared to entity ids,
# PRD §2.1). Safe for any call that is not segregation-of-duties sensitive.
TEST_USERS = {
    "plant_admin_headers": build_user_headers("admin-001", "PlantAdmin"),
    "formulation_scientist_headers": build_user_headers("sci-001", "FormulationScientist"),
    "quality_manager_headers": build_user_headers("qm-001", "QualityManager"),
    "production_planner_headers": build_user_headers("pp-001", "ProductionPlanner"),
    "lab_technician_headers": build_user_headers("lt-001", "LabTechnician"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "brand_customer_rep_headers": build_user_headers("test-rep-1", "BrandCustomerRep"),
}


# Per-instance builders. For BrandCustomerRep (entity-backed identity), pass the
# actual BrandCustomer.id as user_id whenever the call is ownership-gated (§2.1).
def make_plant_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_formulation_scientist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FormulationScientist")


def make_quality_manager_headers(user_id: str) -> dict:
    """QualityManager is opaque, but SoD pairs compare X-User-ID values, so
    validators/deciders must use a user id distinct from the recorder's."""
    return build_user_headers(user_id, "QualityManager")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_lab_technician_headers(user_id: str) -> dict:
    """LabTechnician is opaque, but SoD pairs compare X-User-ID values, so the
    swab/QC recorder's user id must differ from the validator/decider's."""
    return build_user_headers(user_id, "LabTechnician")


def make_brand_customer_rep_headers(user_id: str) -> dict:
    """For BrandCustomerRep (entity-backed: BrandCustomer). Pass the actual
    BrandCustomer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "BrandCustomerRep")
