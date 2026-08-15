"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The Grower role is entity-backed (X-User-ID must be the Grower
# entity's id), so its shared constant is only a fallback for tests that do
# not exercise ownership scoping.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "BuyingPointAdmin"),
    "inspector_headers": build_user_headers("insp-1", "GradingInspector"),
    "inspector_2_headers": build_user_headers("insp-2", "GradingInspector"),
    "lab_tech_headers": build_user_headers("lab-1", "LabTechnician"),
    "lab_tech_2_headers": build_user_headers("lab-2", "LabTechnician"),
    "clerk_1_headers": build_user_headers("clerk-1", "SettlementClerk"),
    "clerk_2_headers": build_user_headers("clerk-2", "SettlementClerk"),
    "clerk_3_headers": build_user_headers("clerk-3", "SettlementClerk"),
    "sheller_rep_headers": build_user_headers("sheller-acme", "ShellerRep"),
    # Fallback only: never use for ownership-gated Grower calls.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


# Per-instance builders — required for entity-backed roles and for any flow
# where the X-User-ID value itself is asserted (segregation of duties).
def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "BuyingPointAdmin")


def make_grower_headers(user_id: str) -> dict:
    """Grower is entity-backed: pass the actual Grower.id as user_id."""
    return build_user_headers(user_id, "Grower")


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GradingInspector")


def make_lab_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementClerk")


def make_sheller_rep_headers(user_id: str) -> dict:
    """ShellerRep ownership anchors on ShellerContract.sheller_ref == X-User-ID."""
    return build_user_headers(user_id, "ShellerRep")
