"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are opaque: the server never compares X-User-ID to an entity id.
The places an operator identifier is persisted and later compared are the
segregation-of-duties anchors (ballot-measure draft/certify, amendment
submit/approve) and audit stamps (published_by_user_id) — tests control the
user id explicitly via the per-role builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "budget_analyst_headers": build_user_headers("test-analyst-1", "BudgetAnalyst"),
    "business_manager_headers": build_user_headers("test-manager-1", "BusinessManager"),
    "board_clerk_headers": build_user_headers("test-clerk-1", "BoardClerk"),
    "superintendent_headers": build_user_headers("test-superintendent-1", "Superintendent"),
    "district_treasurer_headers": build_user_headers("test-treasurer-1", "DistrictTreasurer"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_budget_analyst_headers(user_id: str) -> dict:
    """BudgetAnalyst headers with a specific X-User-ID (e.g. an amendment
    submitter in a segregation-of-duties pair)."""
    return build_user_headers(user_id, "BudgetAnalyst")


def make_business_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BusinessManager")


def make_board_clerk_headers(user_id: str) -> dict:
    """BoardClerk headers with a specific X-User-ID (e.g. ballot drafter vs
    certifier in a segregation-of-duties pair)."""
    return build_user_headers(user_id, "BoardClerk")


def make_superintendent_headers(user_id: str) -> dict:
    """Superintendent headers with a specific X-User-ID (e.g. an amendment
    approver in a segregation-of-duties pair)."""
    return build_user_headers(user_id, "Superintendent")


def make_district_treasurer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistrictTreasurer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
