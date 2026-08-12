"""Pre-built role headers for every role in the PRD (§2.1).

All nine roles use opaque operator identifiers (PRD §2.1): X-User-ID is never
compared to any entity id, but it IS recorded on two-key chains (proposed_by /
adopted_by, prepared_by / reviewed_by, reconciler vs settler, pool closer vs
true-up operator). The make_*_headers builders exist so segregation-of-duties
tests can pin exact operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "board_director_headers": build_user_headers("director-1", "BoardDirector"),
    "rate_analyst_headers": build_user_headers("analyst-1", "RateAnalyst"),
    "program_operator_headers": build_user_headers("operator-1", "ProgramOperator"),
    "customer_service_headers": build_user_headers("csr-1", "CustomerService"),
    "portfolio_manager_headers": build_user_headers("pm-1", "PortfolioManager"),
    "billing_coordinator_headers": build_user_headers("bc-1", "BillingCoordinator"),
    "finance_controller_headers": build_user_headers("fc-1", "FinanceController"),
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "utility_liaison_headers": build_user_headers("liaison-1", "UtilityLiaison"),
}


def make_board_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardDirector")


def make_rate_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RateAnalyst")


def make_program_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramOperator")


def make_customer_service_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CustomerService")


def make_portfolio_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortfolioManager")


def make_billing_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingCoordinator")


def make_finance_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_utility_liaison_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UtilityLiaison")
