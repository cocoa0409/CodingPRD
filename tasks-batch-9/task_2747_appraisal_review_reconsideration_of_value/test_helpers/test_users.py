"""
Pre-built request headers for each role of the Lender Appraisal Review Desk API.

Four roles are opaque: any stable, non-empty identifier is accepted for
LoanOfficer, AppraisalDeskReviewer, ChiefAppraiser and ComplianceOfficer, so this
module pins one constant identifier per opaque role plus spare identifiers where a
test needs two distinct people in the same role (for example a submitter and a
different decider).

Three roles are entity-backed: an AMCCoordinator's ``X-User-ID`` must be the AMC
id, an Appraiser's must be the appraiser id, and a Borrower's must be the loan file
id. Those roles therefore get builder functions rather than constants -- a test
must thread the freshly created resource id through ``make_amc_headers`` and
friends, because no constant can be correct for a resource minted at run time.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Opaque-role identifiers
# ---------------------------------------------------------------------------
LO_USER_1 = "lo_user_1"
LO_USER_2 = "lo_user_2"
DESK_USER_1 = "desk_user_1"
DESK_USER_2 = "desk_user_2"
CHIEF_USER_1 = "chief_user_1"
CHIEF_USER_2 = "chief_user_2"
COMPLIANCE_USER_1 = "compliance_user_1"
COMPLIANCE_USER_2 = "compliance_user_2"

LOAN_OFFICER_HEADERS = build_user_headers(LO_USER_1, Role.LOAN_OFFICER)
LOAN_OFFICER_HEADERS_2 = build_user_headers(LO_USER_2, Role.LOAN_OFFICER)
DESK_REVIEWER_HEADERS = build_user_headers(DESK_USER_1, Role.APPRAISAL_DESK_REVIEWER)
DESK_REVIEWER_HEADERS_2 = build_user_headers(DESK_USER_2, Role.APPRAISAL_DESK_REVIEWER)
CHIEF_APPRAISER_HEADERS = build_user_headers(CHIEF_USER_1, Role.CHIEF_APPRAISER)
CHIEF_APPRAISER_HEADERS_2 = build_user_headers(CHIEF_USER_2, Role.CHIEF_APPRAISER)
COMPLIANCE_HEADERS = build_user_headers(COMPLIANCE_USER_1, Role.COMPLIANCE_OFFICER)
COMPLIANCE_HEADERS_2 = build_user_headers(COMPLIANCE_USER_2, Role.COMPLIANCE_OFFICER)

TEST_USERS: Dict[str, Dict[str, str]] = {
    Role.LOAN_OFFICER: LOAN_OFFICER_HEADERS,
    Role.APPRAISAL_DESK_REVIEWER: DESK_REVIEWER_HEADERS,
    Role.CHIEF_APPRAISER: CHIEF_APPRAISER_HEADERS,
    Role.COMPLIANCE_OFFICER: COMPLIANCE_HEADERS,
}


# ---------------------------------------------------------------------------
# Entity-backed role builders
# ---------------------------------------------------------------------------
def make_amc_headers(amc_id: str) -> Dict[str, str]:
    """Headers for an AMCCoordinator acting for the AMC whose id is ``amc_id``."""
    return build_user_headers(amc_id, Role.AMC_COORDINATOR)


def make_appraiser_headers(appraiser_id: str) -> Dict[str, str]:
    """Headers for an Appraiser acting as the appraiser whose id is ``appraiser_id``."""
    return build_user_headers(appraiser_id, Role.APPRAISER)


def make_borrower_headers(loan_file_id: str) -> Dict[str, str]:
    """Headers for a Borrower acting as the party to loan file ``loan_file_id``."""
    return build_user_headers(loan_file_id, Role.BORROWER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identifier / role pair, for authentication and authorisation checks."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Malformed identity headers
# ---------------------------------------------------------------------------
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": Role.CHIEF_APPRAISER,
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS = {
    "X-User-ID": CHIEF_USER_1,
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": Role.CHIEF_APPRAISER,
    "Content-Type": "application/json",
}
EMPTY_ROLE_HEADERS = {
    "X-User-ID": CHIEF_USER_1,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers(CHIEF_USER_1, "UnderwritingManager")
