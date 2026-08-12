"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for CustomerRep tests that do not
# exercise ownership (e.g. role-denial checks). For any CustomerRep call whose
# success depends on owning the subject resource, use make_customer_rep_headers()
# with the actual Customer id instead.
TEST_USERS = {
    "plant_director_headers": build_user_headers("test-director-1", "PlantDirector"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "qa_manager_headers": build_user_headers("qa-1", "QAManager"),
    "qa_manager_1_headers": build_user_headers("qa-1", "QAManager"),
    "qa_manager_2_headers": build_user_headers("qa-2", "QAManager"),
    "formulation_chemist_headers": build_user_headers("test-chemist-1", "FormulationChemist"),
    "regulatory_affairs_headers": build_user_headers("test-regaff-1", "RegulatoryAffairs"),
    # entity_backed role: fallback for non-ownership tests only (PRD §2.1).
    "customer_rep_headers": build_user_headers("test-customer-1", "CustomerRep"),
}


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed: X-User-ID must equal the acting Customer's id
    whenever the call is ownership-gated (order placement, own-record reads,
    variant waivers, shortfall commits)."""
    return build_user_headers(customer_id, "CustomerRep")


def make_qa_manager_headers(user_id: str) -> dict:
    """QAManager is an opaque operator role; distinct user ids matter for the
    batch-release segregation-of-duties gate (PRD §3.6)."""
    return build_user_headers(user_id, "QAManager")
