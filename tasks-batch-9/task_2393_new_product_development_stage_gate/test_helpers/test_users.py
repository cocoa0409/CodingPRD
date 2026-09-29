"""Pre-built role headers for every role in the PRD.

Actor identity is opaque for all seven roles: ``X-User-ID`` is never a foreign key.
The shared constants below are therefore the canonical form for most calls; the
per-role builders exist so a test can thread *distinct* opaque identifiers when a
segregation-of-duties rule compares recorded identifier strings against each other.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "portfolio_admin_headers": build_user_headers("admin-1", "PortfolioAdmin"),
    "innovation_lead_headers": build_user_headers("lead-1", "InnovationLead"),
    "gate_chair_headers": build_user_headers("chair-1", "GateChair"),
    "functional_reviewer_headers": build_user_headers("reviewer-1", "FunctionalReviewer"),
    "regulatory_approver_headers": build_user_headers("regulatory-1", "RegulatoryApprover"),
    "rnd_lead_headers": build_user_headers("rnd-1", "RnDLead"),
    "sales_account_manager_headers": build_user_headers("sales-1", "SalesAccountManager"),
}

ROLE_NAMES = [
    "PortfolioAdmin",
    "InnovationLead",
    "GateChair",
    "FunctionalReviewer",
    "RegulatoryApprover",
    "RnDLead",
    "SalesAccountManager",
]

ALL_ROLE_HEADERS = [
    TEST_USERS["portfolio_admin_headers"],
    TEST_USERS["innovation_lead_headers"],
    TEST_USERS["gate_chair_headers"],
    TEST_USERS["functional_reviewer_headers"],
    TEST_USERS["regulatory_approver_headers"],
    TEST_USERS["rnd_lead_headers"],
    TEST_USERS["sales_account_manager_headers"],
]


def make_portfolio_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortfolioAdmin")


def make_innovation_lead_headers(user_id: str) -> dict:
    """The creating lead's identifier is recorded as the project's owner_user_id."""
    return build_user_headers(user_id, "InnovationLead")


def make_gate_chair_headers(user_id: str) -> dict:
    """The closing chair's identifier is recorded as the review's chair_user_id."""
    return build_user_headers(user_id, "GateChair")


def make_functional_reviewer_headers(user_id: str) -> dict:
    """A reviewer's identifier is recorded as voter_user_id or decided_by_user_id."""
    return build_user_headers(user_id, "FunctionalReviewer")


def make_regulatory_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryApprover")


def make_rnd_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RnDLead")


def make_sales_account_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesAccountManager")
