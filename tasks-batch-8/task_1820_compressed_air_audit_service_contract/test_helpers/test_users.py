"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For the entity-backed FacilityManager role, prefer
# make_facility_manager_headers(facility["id"]) on any ownership-gated call.
TEST_USERS = {
    "dealer_admin_headers": build_user_headers("test-admin-1", "DealerAdmin"),
    "energy_engineer_headers": build_user_headers("test-eng-1", "EnergyEngineer"),
    "service_tech_headers": build_user_headers("test-tech-1", "ServiceTech"),
    "contract_manager_headers": build_user_headers("test-cm-1", "ContractManager"),
    # Fallback for non-ownership tests only — see make_facility_manager_headers.
    "facility_manager_headers": build_user_headers("test-fm-1", "FacilityManager"),
}


def make_dealer_admin_headers(user_id: str = "test-admin-1") -> dict:
    """DealerAdmin is opaque; user id is only actor-stamped."""
    return build_user_headers(user_id, "DealerAdmin")


def make_energy_engineer_headers(user_id: str = "eng-1") -> dict:
    """EnergyEngineer is opaque; user id is actor-stamped and compared by
    segregation-of-duties rules (survey verify, measurement close)."""
    return build_user_headers(user_id, "EnergyEngineer")


def make_service_tech_headers(user_id: str = "tech-1") -> dict:
    """ServiceTech is opaque; user id is actor-stamped."""
    return build_user_headers(user_id, "ServiceTech")


def make_contract_manager_headers(user_id: str = "test-cm-1") -> dict:
    """ContractManager is opaque; user id is only actor-stamped."""
    return build_user_headers(user_id, "ContractManager")


def make_facility_manager_headers(facility_id: str) -> dict:
    """FacilityManager is entity-backed (PRD §2.1): X-User-ID must equal the id
    of the Facility that owns the acted-upon resource. Always pass the actual
    Facility.id for ownership-gated calls."""
    return build_user_headers(facility_id, "FacilityManager")
