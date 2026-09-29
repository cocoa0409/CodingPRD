"""Identity headers for the seven declared roles.

PRD §2.1 requires every request to carry `X-User-ID` and `X-User-Role`. Two of
the seven roles are entity-backed: a `Borrower` caller's `X-User-ID` must equal
the `Borrower.id` it is acting for and a `Contractor` caller's `X-User-ID` must
equal the `Contractor.id`; a mismatch is `ERR_NOT_OWNER`. Those two roles
therefore get header *builders* rather than fixed constants.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# The five opaque roles — any stable identifier works for them.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "loan_officer": build_user_headers("lo-01", UserRole.LOAN_OFFICER.value),
    "loan_officer_2": build_user_headers("lo-02", UserRole.LOAN_OFFICER.value),
    "credit_committee": build_user_headers("cc-01", UserRole.CREDIT_COMMITTEE.value),
    "credit_committee_2": build_user_headers("cc-02", UserRole.CREDIT_COMMITTEE.value),
    "servicer": build_user_headers("svc-01", UserRole.LOAN_SERVICER.value),
    "servicer_2": build_user_headers("svc-02", UserRole.LOAN_SERVICER.value),
    "servicer_3": build_user_headers("svc-03", UserRole.LOAN_SERVICER.value),
    "inspector": build_user_headers("insp-01", UserRole.DRAW_INSPECTOR.value),
    "inspector_2": build_user_headers("insp-02", UserRole.DRAW_INSPECTOR.value),
    "inspector_3": build_user_headers("insp-03", UserRole.DRAW_INSPECTOR.value),
    "inspector_9": build_user_headers("insp-09", UserRole.DRAW_INSPECTOR.value),
    "platform_admin": build_user_headers("admin-01", UserRole.PLATFORM_ADMIN.value),
}

# Convenience aliases used throughout the suite.
LOAN_OFFICER = TEST_USERS["loan_officer"]
LOAN_OFFICER_2 = TEST_USERS["loan_officer_2"]
CREDIT_COMMITTEE = TEST_USERS["credit_committee"]
CREDIT_COMMITTEE_2 = TEST_USERS["credit_committee_2"]
SERVICER = TEST_USERS["servicer"]
SERVICER_2 = TEST_USERS["servicer_2"]
SERVICER_3 = TEST_USERS["servicer_3"]
INSPECTOR = TEST_USERS["inspector"]
INSPECTOR_2 = TEST_USERS["inspector_2"]
INSPECTOR_3 = TEST_USERS["inspector_3"]
INSPECTOR_9 = TEST_USERS["inspector_9"]
PLATFORM_ADMIN = TEST_USERS["platform_admin"]

INSPECTOR_IDS = {
    "insp-01": INSPECTOR,
    "insp-02": INSPECTOR_2,
    "insp-03": INSPECTOR_3,
    "insp-09": INSPECTOR_9,
}


def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """Headers for a `Borrower` caller acting on its own sponsor row."""
    return build_user_headers(borrower_id, UserRole.BORROWER.value)


def make_contractor_headers(contractor_id: str) -> Dict[str, str]:
    """Headers for a `Contractor` caller acting on its own contractor row."""
    return build_user_headers(contractor_id, UserRole.CONTRACTOR.value)


def make_loan_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.LOAN_OFFICER.value)


def make_credit_committee_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CREDIT_COMMITTEE.value)


def make_servicer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.LOAN_SERVICER.value)


def make_inspector_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.DRAW_INSPECTOR.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = "lo-01") -> Dict[str, str]:
    """Headers whose `X-User-Role` is absent entirely (PRD §2.1 → 401)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(
    user_id: str = "lo-01", role: str = "Underwriter"
) -> Dict[str, str]:
    """Headers naming a role that is not one of the seven (PRD §2.1 → 401)."""
    return build_user_headers(user_id, role)
