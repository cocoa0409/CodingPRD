"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers: X-User-ID is never compared
against any entity id. Segregation-of-duties rules compare one operator's
X-User-ID against another's, so distinct named users are provided per role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_operator_headers": build_user_headers("sysop-1", "SystemOperator"),
    "capital_analyst_headers": build_user_headers("analyst-1", "CapitalAnalyst"),
    "regulator_reviewer_headers": build_user_headers("regulator-1", "RegulatorReviewer"),
    "board_approver_headers": build_user_headers("board-1", "BoardApprover"),
    "external_auditor_headers": build_user_headers("auditor-1", "ExternalAuditor"),
}


def make_system_operator_headers(user_id: str = "sysop-1") -> dict:
    """SystemOperator headers with a chosen user id."""
    return build_user_headers(user_id, "SystemOperator")


def make_capital_analyst_headers(user_id: str) -> dict:
    """CapitalAnalyst headers with a chosen user id.

    Use a distinct user id whenever segregation-of-duties applies (the
    submitter must differ from the preparer on call reports; the plan
    preparer and board approver must differ; the ICAAP preparer and
    attester must differ).
    """
    return build_user_headers(user_id, "CapitalAnalyst")


def make_regulator_reviewer_headers(user_id: str = "regulator-1") -> dict:
    """RegulatorReviewer headers with a chosen user id."""
    return build_user_headers(user_id, "RegulatorReviewer")


def make_board_approver_headers(user_id: str = "board-1") -> dict:
    """BoardApprover headers with a chosen user id (must differ from the
    analyst who prepared the plan / ICAAP document)."""
    return build_user_headers(user_id, "BoardApprover")


def make_external_auditor_headers(user_id: str = "auditor-1") -> dict:
    """ExternalAuditor headers with a chosen user id."""
    return build_user_headers(user_id, "ExternalAuditor")
