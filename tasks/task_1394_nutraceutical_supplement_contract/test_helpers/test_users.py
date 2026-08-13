"""Pre-built role headers for every role in the PRD (§2.1).

BrandRep identity is entity-backed: its X-User-ID must be the acting Customer's
`id`, so ownership-gated calls must use make_brandrep_headers(customer["id"]).
The other four roles carry opaque operator identifiers (PRD §2.1); per-call
builders exist so segregation-of-duties scenarios (PRD §2.10) can thread
distinct or shared identities.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    DEFAULT_CHEMIST_ID,
    DEFAULT_OPERATOR_ID,
    DEFAULT_QA_MANAGER_ID,
)

# Shared constants — safe for opaque roles, and for tests that do not depend on
# the caller owning the subject resource. The BrandRep shared constant is a
# fallback for non-ownership tests only (e.g., 400/404/RBAC checks).
TEST_USERS = {
    "brand_rep_headers": build_user_headers("test-brandrep-1", "BrandRep"),
    "production_planner_headers": build_user_headers("planner-1", "ProductionPlanner"),
    "production_operator_headers": build_user_headers(DEFAULT_OPERATOR_ID, "ProductionOperator"),
    "qa_chemist_headers": build_user_headers(DEFAULT_CHEMIST_ID, "QAChemist"),
    "qa_manager_headers": build_user_headers(DEFAULT_QA_MANAGER_ID, "QAManager"),
}


def make_brandrep_headers(user_id: str) -> dict:
    """BrandRep is entity-backed by Customer: pass the actual Customer.id as
    user_id whenever the call is ownership-gated (order placement/cancel)."""
    return build_user_headers(user_id, "BrandRep")


def make_production_planner_headers(user_id: str = "planner-1") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_production_operator_headers(user_id: str = DEFAULT_OPERATOR_ID) -> dict:
    return build_user_headers(user_id, "ProductionOperator")


def make_qa_chemist_headers(user_id: str = DEFAULT_CHEMIST_ID) -> dict:
    return build_user_headers(user_id, "QAChemist")


def make_qa_manager_headers(user_id: str = DEFAULT_QA_MANAGER_ID) -> dict:
    return build_user_headers(user_id, "QAManager")
