"""Pre-built role headers for every role in the PRD.

All eleven roles carry an opaque identity: `X-User-ID` is an operator
identifier the server never compares to any row's `id`. The server only
*records* it and later compares recorded values to each other — which is why
the per-role builders below matter wherever a separation-of-duties or
order-ownership comparison is in play.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used across the suite. Where two identifiers
# exist for one role, the pair exists so that a separation-of-duties rule can
# be satisfied (two different people) or deliberately violated (same person).
USER_IDS = {
    "plant_admin": "user-pa-1",
    "design_engineer": "user-de-1",
    "reliability_engineer": "user-re-1",
    "reliability_engineer_2": "user-re-2",
    "certification_engineer": "user-ce-1",
    "certification_engineer_2": "user-ce-2",
    "regulatory_auditor": "user-ra-1",
    "supply_planner": "user-sp-1",
    "production_planner": "user-pp-1",
    "production_technician": "user-pt-1",
    "quality_technician": "user-qt-1",
    "quality_technician_2": "user-qt-2",
    "distributor_rep": "user-dr-1",
    "distributor_rep_2": "user-dr-2",
    "distributor_rep_3": "user-dr-3",
    "warranty_analyst": "user-wa-1",
}

ROLE_NAMES = {
    "plant_admin": "PlantAdmin",
    "design_engineer": "DesignEngineer",
    "reliability_engineer": "ReliabilityEngineer",
    "certification_engineer": "CertificationEngineer",
    "regulatory_auditor": "RegulatoryAuditor",
    "supply_planner": "SupplyPlanner",
    "production_planner": "ProductionPlanner",
    "production_technician": "ProductionTechnician",
    "quality_technician": "QualityTechnician",
    "distributor_rep": "DistributorRep",
    "warranty_analyst": "WarrantyAnalyst",
}


TEST_USERS = {
    "plant_admin_headers": build_user_headers(USER_IDS["plant_admin"], "PlantAdmin"),
    "design_engineer_headers": build_user_headers(
        USER_IDS["design_engineer"], "DesignEngineer"
    ),
    "reliability_engineer_headers": build_user_headers(
        USER_IDS["reliability_engineer"], "ReliabilityEngineer"
    ),
    "reliability_engineer_2_headers": build_user_headers(
        USER_IDS["reliability_engineer_2"], "ReliabilityEngineer"
    ),
    "certification_engineer_headers": build_user_headers(
        USER_IDS["certification_engineer"], "CertificationEngineer"
    ),
    "certification_engineer_2_headers": build_user_headers(
        USER_IDS["certification_engineer_2"], "CertificationEngineer"
    ),
    "regulatory_auditor_headers": build_user_headers(
        USER_IDS["regulatory_auditor"], "RegulatoryAuditor"
    ),
    "supply_planner_headers": build_user_headers(
        USER_IDS["supply_planner"], "SupplyPlanner"
    ),
    "production_planner_headers": build_user_headers(
        USER_IDS["production_planner"], "ProductionPlanner"
    ),
    "production_technician_headers": build_user_headers(
        USER_IDS["production_technician"], "ProductionTechnician"
    ),
    "quality_technician_headers": build_user_headers(
        USER_IDS["quality_technician"], "QualityTechnician"
    ),
    "quality_technician_2_headers": build_user_headers(
        USER_IDS["quality_technician_2"], "QualityTechnician"
    ),
    "distributor_rep_headers": build_user_headers(
        USER_IDS["distributor_rep"], "DistributorRep"
    ),
    "distributor_rep_2_headers": build_user_headers(
        USER_IDS["distributor_rep_2"], "DistributorRep"
    ),
    "distributor_rep_3_headers": build_user_headers(
        USER_IDS["distributor_rep_3"], "DistributorRep"
    ),
    "warranty_analyst_headers": build_user_headers(
        USER_IDS["warranty_analyst"], "WarrantyAnalyst"
    ),
}


# --- Per-instance builders -------------------------------------------------
# Use these whenever a call's outcome depends on WHICH operator acts: the four
# separation-of-duties comparisons and the order-ownership comparison.


def make_plant_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_design_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DesignEngineer")


def make_reliability_engineer_headers(user_id: str) -> dict:
    """Pass the identifier that must differ from a platform's
    submitted_by_user_id, or from a cited claim's filed_by_user_id."""
    return build_user_headers(user_id, "ReliabilityEngineer")


def make_certification_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CertificationEngineer")


def make_regulatory_auditor_headers(user_id: str) -> dict:
    """Pass the identifier that must differ from a filing's
    submitted_by_user_id."""
    return build_user_headers(user_id, "RegulatoryAuditor")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_production_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionTechnician")


def make_quality_technician_headers(user_id: str) -> dict:
    """Pass the identifier that must differ from the performed_by_user_id of
    the lot's most recent passing leak test when recording a run test."""
    return build_user_headers(user_id, "QualityTechnician")


def make_distributor_rep_headers(user_id: str) -> dict:
    """Pass the identifier that must equal a distributor order's
    created_by_user_id when cancelling it."""
    return build_user_headers(user_id, "DistributorRep")


def make_warranty_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarrantyAnalyst")


def make_headers(user_id: str, role: str) -> dict:
    """Generic builder for a caller identified by user_id acting as role."""
    return build_user_headers(user_id, role)
