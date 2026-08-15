"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed:Surgeon — fallback for non-ownership tests only.
    "surgeon_headers": build_user_headers("test-surgeon-1", "Surgeon"),
    # opaque roles: shared constant is the canonical form.
    "analyst_headers": build_user_headers("test-analyst-1", "SupplyChainAnalyst"),
    "cart_tech_headers": build_user_headers("test-cart-tech-1", "CartTechnician"),
    "nurse_headers": build_user_headers("test-nurse-1", "CirculatingNurse"),
    "officer_1_headers": build_user_headers("officer-1", "ValueAnalysisOfficer"),
    "officer_2_headers": build_user_headers("officer-2", "ValueAnalysisOfficer"),
    "materials_headers": build_user_headers("test-materials-1", "MaterialsManager"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


# Per-instance builder — required for the entity_backed Surgeon role.
def make_surgeon_headers(user_id: str) -> dict:
    """For Surgeon (entity_backed:Surgeon). Pass the actual Surgeon.id as user_id
    whenever the call is ownership-gated (product-request create, audit dispute)."""
    return build_user_headers(user_id, "Surgeon")


def make_officer_headers(user_id: str) -> dict:
    """For ValueAnalysisOfficer (opaque). Use a distinct id per officer when
    exercising endorsement quorum / SoD rules."""
    return build_user_headers(user_id, "ValueAnalysisOfficer")
