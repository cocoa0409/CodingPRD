"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the nine opaque roles, whose X-User-ID is not
# compared to any entity id (PRD §2.1). The GrowerRep shared constant is only a
# fallback for tests that do not exercise ownership scoping.
TEST_USERS = {
    "mill_admin_headers": build_user_headers("test-mill-admin-1", "MillAdmin"),
    "merchandiser_headers": build_user_headers("test-merchandiser-1", "Merchandiser"),
    "scale_operator_headers": build_user_headers("test-scale-operator-1", "ScaleOperator"),
    "quality_lab_tech_headers": build_user_headers("test-quality-lab-tech-1", "QualityLabTech"),
    "dryer_operator_headers": build_user_headers("test-dryer-operator-1", "DryerOperator"),
    "mill_supervisor_headers": build_user_headers("test-mill-supervisor-1", "MillSupervisor"),
    # SettlementClerk is opaque, but settlement approval compares X-User-ID to the
    # settlement's created_by_user_id (segregation of duties), so two stable clerk
    # identities are provided.
    "settlement_clerk_headers": build_user_headers("clerk-1", "SettlementClerk"),
    "settlement_clerk_2_headers": build_user_headers("clerk-2", "SettlementClerk"),
    "grower_rep_headers": build_user_headers("test-grower-rep-1", "GrowerRep"),
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    "fumigation_tech_headers": build_user_headers("test-fumigation-tech-1", "FumigationTech"),
}


def make_grower_rep_headers(grower_id: str) -> dict:
    """GrowerRep is entity-backed: X-User-ID must be the acting Grower's id
    whenever the call is ownership-scoped (PRD §2.1)."""
    return build_user_headers(grower_id, "GrowerRep")


def make_clerk_headers(user_id: str) -> dict:
    """SettlementClerk headers with a specific operator identity, for the
    segregation-of-duties approval check (PRD §2.1, §3.8)."""
    return build_user_headers(user_id, "SettlementClerk")
