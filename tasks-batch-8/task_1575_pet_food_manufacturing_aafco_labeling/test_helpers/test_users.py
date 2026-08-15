"""Pre-built role headers for every role in the PRD (§2.1).

RegulatoryAffairs is entity-backed: its X-User-ID must be the id of the acting
BrandOwner (PRD §2.1). Use make_regulatory_affairs_headers(brand_owner_id) for
any ownership-gated call; the shared constant is a fallback only for tests that
do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "formulation_scientist_headers": build_user_headers(
        "test-formulation-scientist-1", "FormulationScientist"
    ),
    "qa_approver_headers": build_user_headers("test-qa-approver-1", "QAApprover"),
    "quality_analyst_headers": build_user_headers("test-quality-analyst-1", "QualityAnalyst"),
    "trial_coordinator_headers": build_user_headers("test-trial-coordinator-1", "TrialCoordinator"),
    "production_planner_headers": build_user_headers(
        "test-production-planner-1", "ProductionPlanner"
    ),
    "line_operator_headers": build_user_headers("test-line-operator-1", "LineOperator"),
    # Fallback for non-ownership calls only; prefer make_regulatory_affairs_headers.
    "regulatory_affairs_headers": build_user_headers(
        "test-regulatory-affairs-1", "RegulatoryAffairs"
    ),
    "state_regulator_headers": build_user_headers("test-state-regulator-1", "StateRegulator"),
}


def make_regulatory_affairs_headers(brand_owner_id: str) -> dict:
    """RegulatoryAffairs is entity-backed by BrandOwner: X-User-ID must be the
    acting BrandOwner's id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(brand_owner_id, "RegulatoryAffairs")


def make_qa_approver_headers(user_id: str) -> dict:
    """QAApprover with a specific X-User-ID (segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "QAApprover")


def make_quality_analyst_headers(user_id: str) -> dict:
    """QualityAnalyst with a specific X-User-ID (segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "QualityAnalyst")
