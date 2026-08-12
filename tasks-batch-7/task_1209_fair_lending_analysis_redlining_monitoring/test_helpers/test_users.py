"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. The entity-backed LoanOfficer role additionally exposes a
per-instance builder: pass the actual LoanOfficer id as user_id whenever the
call is ownership-gated (exception/override creation, withdraw, dispute).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "bank_admin_headers": build_user_headers("test-admin-1", "BankAdmin"),
    "data_ops_headers": build_user_headers("test-dataops-1", "LendingDataOps"),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls MUST use make_loan_officer_headers().
    "loan_officer_headers": build_user_headers("test-officer-1", "LoanOfficer"),
    "analyst_headers": build_user_headers("test-analyst-1", "FairLendingAnalyst"),
    "officer_headers": build_user_headers("test-flofficer-1", "FairLendingOfficer"),
    "director_headers": build_user_headers("test-director-1", "ComplianceDirector"),
    "specialist_headers": build_user_headers("test-specialist-1", "RemediationSpecialist"),
}


def make_bank_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BankAdmin")


def make_data_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LendingDataOps")


def make_loan_officer_headers(user_id: str) -> dict:
    """For the entity-backed LoanOfficer role. Pass the actual LoanOfficer.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "LoanOfficer")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FairLendingAnalyst")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FairLendingOfficer")


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceDirector")


def make_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RemediationSpecialist")
