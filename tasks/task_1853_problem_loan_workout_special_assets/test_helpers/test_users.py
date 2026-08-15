"""Pre-built role headers for every role in the PRD.

All eight roles are opaque per PRD §2.1: X-User-ID is not tied to any persisted
entity's id. Segregation-of-duties comparisons, however, compare X-User-ID
strings against the case's recorded case_officer_id, so builders are provided
to thread a chosen user id through a scenario.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "workout_officer_headers": build_user_headers("officer-default", "WorkoutOfficer"),
    "special_assets_manager_headers": build_user_headers("mgr-default", "SpecialAssetsManager"),
    "credit_committee_headers": build_user_headers("cc-default", "CreditCommittee"),
    "appraisal_desk_headers": build_user_headers("appr-default", "AppraisalDesk"),
    "legal_counsel_headers": build_user_headers("counsel-default", "LegalCounsel"),
    "loan_accounting_headers": build_user_headers("acct-default", "LoanAccounting"),
    "portfolio_analyst_headers": build_user_headers("analyst-default", "PortfolioAnalyst"),
    "system_admin_headers": build_user_headers("admin-default", "SystemAdmin"),
}


def make_workout_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WorkoutOfficer")


def make_special_assets_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SpecialAssetsManager")


def make_credit_committee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditCommittee")


def make_appraisal_desk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppraisalDesk")


def make_legal_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_loan_accounting_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LoanAccounting")


def make_portfolio_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortfolioAnalyst")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
