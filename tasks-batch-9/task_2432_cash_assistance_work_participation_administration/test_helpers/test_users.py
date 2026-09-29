"""Acting identities and their request headers.

Operator roles carry opaque user identifiers. The ``Applicant`` role is
different: its ``X-User-ID`` must be the ``id`` of the acting household,
because ownership checks compare that header against the resource's household
foreign key. Use :func:`make_applicant_headers` for every applicant call.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Operator identities ----------------------------------------------------
CASEWORKER_ID = "cw-1"
CASEWORKER_ALT_ID = "cw-2"
SUPERVISOR_ID = "sup-1"
SUPERVISOR_ALT_ID = "sup-2"
WORK_SPECIALIST_ID = "wps-1"
WORK_SPECIALIST_ALT_ID = "wps-2"
FISCAL_OFFICER_ID = "fo-1"
FISCAL_OFFICER_ALT_ID = "fo-2"
FRAUD_INVESTIGATOR_ID = "fi-1"
FRAUD_INVESTIGATOR_ALT_ID = "fi-2"
ANALYST_ID = "an-1"
ANALYST_ALT_ID = "an-2"


def caseworker_headers(user_id: str = CASEWORKER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CASEWORKER.value)


def supervisor_headers(user_id: str = SUPERVISOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ELIGIBILITY_SUPERVISOR.value)


def work_specialist_headers(user_id: str = WORK_SPECIALIST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.WORK_PROGRAM_SPECIALIST.value)


def fiscal_officer_headers(user_id: str = FISCAL_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FISCAL_OFFICER.value)


def fraud_investigator_headers(user_id: str = FRAUD_INVESTIGATOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FRAUD_INVESTIGATOR.value)


def analyst_headers(user_id: str = ANALYST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.STATE_REPORTING_ANALYST.value)


def make_applicant_headers(household_id: str) -> Dict[str, str]:
    """Headers for an applicant acting on behalf of ``household_id``.

    The identifier is the household's own ``id`` so that ownership checks
    resolve to the owning household.
    """
    return build_user_headers(household_id, UserRole.APPLICANT.value)


HEADERS_BY_ROLE = {
    UserRole.CASEWORKER.value: caseworker_headers,
    UserRole.ELIGIBILITY_SUPERVISOR.value: supervisor_headers,
    UserRole.WORK_PROGRAM_SPECIALIST.value: work_specialist_headers,
    UserRole.FISCAL_OFFICER.value: fiscal_officer_headers,
    UserRole.FRAUD_INVESTIGATOR.value: fraud_investigator_headers,
    UserRole.STATE_REPORTING_ANALYST.value: analyst_headers,
}


def headers_for_role(role: str) -> Dict[str, str]:
    """Default headers for any operator role."""
    return HEADERS_BY_ROLE[role]()
