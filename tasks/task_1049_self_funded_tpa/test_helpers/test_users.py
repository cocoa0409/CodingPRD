"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identifiers: the server never compares
X-User-ID to a resource id for ownership. X-User-ID is, however, recorded on a
claim when a ClaimsExaminer pends it and later used to enforce separation of
duties at adjudication — so examiner tests must control the acting user id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tpa_admin_headers": build_user_headers("tpa-admin-1", "TPAAdmin"),
    # Default examiner id is "ex-1" to match the canonical setup flows.
    "claims_examiner_headers": build_user_headers("ex-1", "ClaimsExaminer"),
    "fund_manager_headers": build_user_headers("fund-mgr-1", "FundManager"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TPAAdmin")


def make_examiner_headers(user_id: str) -> dict:
    """Headers for a ClaimsExaminer with a specific X-User-ID. Pass the acting
    examiner id so segregation-of-duties can be exercised (pender vs adjudicator)."""
    return build_user_headers(user_id, "ClaimsExaminer")


def make_fund_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FundManager")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
