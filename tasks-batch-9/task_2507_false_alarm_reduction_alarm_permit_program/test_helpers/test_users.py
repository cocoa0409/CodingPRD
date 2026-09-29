"""Authenticated principals for the eight declared roles.

Six roles are opaque: the identifier is any non-empty string and the API does
not resolve it to a stored row. Two roles are entity-backed and must carry the
identifier of the aggregate they own — AlarmCompanyOperator carries an
AlarmCompany id, AlarmUser carries an AlarmSite id — so those two get builder
functions rather than fixed constants.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------- #
# Opaque principals
# --------------------------------------------------------------------------- #
PROGRAM_ADMIN_ID = "pa-01"
PERMIT_CLERK_ID = "pc-07"
DISPATCH_SUPERVISOR_ID = "pds-05"
REVIEW_OFFICER_ID = "faro-11"
HEARING_OFFICER_ID = "ho-03"
BILLING_CLERK_ID = "bc-02"

# A second principal per opaque seat, for tests that need two distinct humans
# in the same role (docket ownership, four-eyes checks).
PROGRAM_ADMIN_ID_2 = "pa-02"
PERMIT_CLERK_ID_2 = "pc-08"
DISPATCH_SUPERVISOR_ID_2 = "pds-06"
REVIEW_OFFICER_ID_2 = "faro-12"
HEARING_OFFICER_ID_2 = "ho-04"
BILLING_CLERK_ID_2 = "bc-03"

# One human occupying two seats, used to provoke the segregation-of-duties
# refusals: the same identifier acts under two different role names.
DUAL_ROLE_ID = "dual-07"


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Authentication headers for an arbitrary role/identifier pairing."""
    return build_user_headers(user_id, role)


PROGRAM_ADMIN = headers_for(UserRole.PROGRAM_ADMINISTRATOR.value, PROGRAM_ADMIN_ID)
PERMIT_CLERK = headers_for(UserRole.PERMIT_CLERK.value, PERMIT_CLERK_ID)
DISPATCH_SUPERVISOR = headers_for(UserRole.POLICE_DISPATCH_SUPERVISOR.value, DISPATCH_SUPERVISOR_ID)
REVIEW_OFFICER = headers_for(UserRole.FALSE_ALARM_REVIEW_OFFICER.value, REVIEW_OFFICER_ID)
HEARING_OFFICER = headers_for(UserRole.HEARING_OFFICER.value, HEARING_OFFICER_ID)
BILLING_CLERK = headers_for(UserRole.BILLING_CLERK.value, BILLING_CLERK_ID)

PROGRAM_ADMIN_2 = headers_for(UserRole.PROGRAM_ADMINISTRATOR.value, PROGRAM_ADMIN_ID_2)
PERMIT_CLERK_2 = headers_for(UserRole.PERMIT_CLERK.value, PERMIT_CLERK_ID_2)
DISPATCH_SUPERVISOR_2 = headers_for(UserRole.POLICE_DISPATCH_SUPERVISOR.value, DISPATCH_SUPERVISOR_ID_2)
REVIEW_OFFICER_2 = headers_for(UserRole.FALSE_ALARM_REVIEW_OFFICER.value, REVIEW_OFFICER_ID_2)
HEARING_OFFICER_2 = headers_for(UserRole.HEARING_OFFICER.value, HEARING_OFFICER_ID_2)
BILLING_CLERK_2 = headers_for(UserRole.BILLING_CLERK.value, BILLING_CLERK_ID_2)


# --------------------------------------------------------------------------- #
# Entity-backed principals
# --------------------------------------------------------------------------- #
def alarm_company_operator(company_id: str) -> Dict[str, str]:
    """Headers for the operator of one monitoring company."""
    return headers_for(UserRole.ALARM_COMPANY_OPERATOR.value, company_id)


def alarm_user(site_id: str) -> Dict[str, str]:
    """Headers for the permit holder of one premises."""
    return headers_for(UserRole.ALARM_USER.value, site_id)


# --------------------------------------------------------------------------- #
# Malformed / unrecognized principals
# --------------------------------------------------------------------------- #
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PROGRAM_ADMIN_ID,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": UserRole.PROGRAM_ADMINISTRATOR.value,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = headers_for("CityAuditor", "aud-99")

TEST_USERS: Dict[str, Dict[str, str]] = {
    "ProgramAdministrator": PROGRAM_ADMIN,
    "PermitClerk": PERMIT_CLERK,
    "PoliceDispatchSupervisor": DISPATCH_SUPERVISOR,
    "FalseAlarmReviewOfficer": REVIEW_OFFICER,
    "HearingOfficer": HEARING_OFFICER,
    "BillingClerk": BILLING_CLERK,
}
