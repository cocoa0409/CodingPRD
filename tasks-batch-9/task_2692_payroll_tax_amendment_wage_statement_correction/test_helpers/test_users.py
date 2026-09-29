"""Per-role request headers.

Every request other than the logical-clock setter carries ``X-User-ID`` and
``X-User-Role``. For the five opaque roles the identifier is any stable string.
For ``EmployerRep`` the identifier must name an existing ``Employer`` row and for
``EmployeeSelfService`` it must name an existing ``Employee`` row, so those two
roles are always built from a captured entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTROLS_AUDITOR,
    ROLE_EMPLOYEE_SELF_SERVICE,
    ROLE_EMPLOYER_REP,
    ROLE_PAYROLL_ANALYST,
    ROLE_PLATFORM_ADMIN,
    ROLE_TAX_OFFICER,
    ROLE_TAX_PREPARER,
)

# Stable opaque user identifiers used across the suite.
USER_ADMIN = "u_admin_one"
USER_ADMIN_ALT = "u_admin_two"
USER_ANALYST = "u_analyst_nia"
USER_PREPARER = "u_prep_alex"
USER_PREPARER_ALT = "u_prep_finn"
USER_OFFICER = "u_sign_bo"
USER_OFFICER_ALT = "u_sign_gray"
USER_AUDITOR = "u_audit_dee"
USER_OWNER_CASS = "u_owner_cass"
USER_OWNER_ELI = "u_owner_eli"

ADMIN_HEADERS = build_user_headers(USER_ADMIN, ROLE_PLATFORM_ADMIN)
ADMIN_ALT_HEADERS = build_user_headers(USER_ADMIN_ALT, ROLE_PLATFORM_ADMIN)
ANALYST_HEADERS = build_user_headers(USER_ANALYST, ROLE_PAYROLL_ANALYST)
PREPARER_HEADERS = build_user_headers(USER_PREPARER, ROLE_TAX_PREPARER)
PREPARER_ALT_HEADERS = build_user_headers(USER_PREPARER_ALT, ROLE_TAX_PREPARER)
OFFICER_HEADERS = build_user_headers(USER_OFFICER, ROLE_TAX_OFFICER)
OFFICER_ALT_HEADERS = build_user_headers(USER_OFFICER_ALT, ROLE_TAX_OFFICER)
AUDITOR_HEADERS = build_user_headers(USER_AUDITOR, ROLE_CONTROLS_AUDITOR)
OWNER_AUDITOR_HEADERS = build_user_headers(USER_OWNER_CASS, ROLE_CONTROLS_AUDITOR)
OWNER_ELI_AUDITOR_HEADERS = build_user_headers(USER_OWNER_ELI, ROLE_CONTROLS_AUDITOR)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PAYROLL_ANALYST)


def make_preparer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TAX_PREPARER)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TAX_OFFICER)


def make_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CONTROLS_AUDITOR)


def make_employer_rep_headers(employer_id: str) -> Dict[str, str]:
    """EmployerRep identity: X-User-ID must name an existing Employer row."""
    return build_user_headers(employer_id, ROLE_EMPLOYER_REP)


def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """EmployeeSelfService identity: X-User-ID must name an existing Employee row."""
    return build_user_headers(employee_id, ROLE_EMPLOYEE_SELF_SERVICE)


def make_role_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role name, including names the PRD never declares."""
    return build_user_headers(user_id, role)


NO_HEADERS: Dict[str, str] = {}

MISSING_ROLE_HEADERS = {"X-User-ID": USER_ADMIN, "Content-Type": "application/json"}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}
EMPTY_ROLE_HEADERS = {
    "X-User-ID": USER_ADMIN,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
