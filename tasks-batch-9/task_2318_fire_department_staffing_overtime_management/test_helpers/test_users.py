"""Auth headers for each role.

The PRD ties ``X-User-ID`` to a persisted member for the ``CompanyOfficer`` and
``Firefighter`` roles: ownership and segregation-of-duties checks compare the
resource's member reference to the header value. Those two roles therefore
always need a per-member header built from a real firefighter id, which is what
``make_company_officer_headers`` and ``make_firefighter_headers`` provide.

``StaffingOfficer`` and ``PayrollAnalyst`` identities are opaque operator
identifiers never compared to any entity id, so a shared constant is correct for
them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque operator identifiers (never compared to an entity id).
STAFFING_OFFICER_USER_ID = "11111111-1111-4111-8111-111111111111"
PAYROLL_ANALYST_USER_ID = "22222222-2222-4222-8222-222222222222"

STAFFING_OFFICER = build_user_headers(
    STAFFING_OFFICER_USER_ID, Role.STAFFING_OFFICER.value
)
PAYROLL_ANALYST = build_user_headers(
    PAYROLL_ANALYST_USER_ID, Role.PAYROLL_ANALYST.value
)


def make_staffing_officer_headers(user_id: str = STAFFING_OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for an operator acting as StaffingOfficer."""
    return build_user_headers(user_id, Role.STAFFING_OFFICER.value)


def make_payroll_analyst_headers(user_id: str = PAYROLL_ANALYST_USER_ID) -> Dict[str, str]:
    """Headers for an operator acting as PayrollAnalyst."""
    return build_user_headers(user_id, Role.PAYROLL_ANALYST.value)


def make_company_officer_headers(firefighter_id: str) -> Dict[str, str]:
    """Headers for a company officer acting as the named member."""
    return build_user_headers(firefighter_id, Role.COMPANY_OFFICER.value)


def make_firefighter_headers(firefighter_id: str) -> Dict[str, str]:
    """Headers for a line member acting on their own resources."""
    return build_user_headers(firefighter_id, Role.FIREFIGHTER.value)


def headers_without_role(user_id: str = STAFFING_OFFICER_USER_ID) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = Role.STAFFING_OFFICER.value) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = STAFFING_OFFICER_USER_ID) -> Dict[str, str]:
    """Headers presenting a role outside the four the PRD defines."""
    return build_user_headers(user_id, "BattalionChief")


ALL_ROLES = [
    Role.STAFFING_OFFICER.value,
    Role.COMPANY_OFFICER.value,
    Role.FIREFIGHTER.value,
    Role.PAYROLL_ANALYST.value,
]
