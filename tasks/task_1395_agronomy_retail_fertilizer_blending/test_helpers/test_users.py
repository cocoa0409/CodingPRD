"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Grower tests that do not
# exercise ownership gating (e.g. payload-shape or not-found probes).
TEST_USERS = {
    # entity_backed role (GrowerAccount): shared constant is a fallback for
    # non-ownership tests only; ownership-gated calls MUST use
    # make_grower_headers(grower["id"]).
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
    # opaque roles: shared constant is the canonical form.
    "agronomist_headers": build_user_headers("test-agronomist-1", "Agronomist"),
    "plant_operator_headers": build_user_headers("test-plant-operator-1", "PlantOperator"),
    "logistics_dispatcher_headers": build_user_headers("test-logistics-dispatcher-1", "LogisticsDispatcher"),
    "credit_manager_headers": build_user_headers("test-credit-manager-1", "CreditManager"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "branch_admin_headers": build_user_headers("test-branch-admin-1", "BranchAdmin"),
}


def make_grower_headers(user_id: str) -> dict:
    """For Grower (entity_backed:GrowerAccount). Pass the actual GrowerAccount.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Grower")
