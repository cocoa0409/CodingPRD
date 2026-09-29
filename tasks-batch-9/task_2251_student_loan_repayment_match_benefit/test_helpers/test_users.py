"""
Auth headers for the five declared roles.

Per PRD §2.1 four of the five roles carry an opaque identity, so a pinned
string id is sufficient for them. The `Employee` role is entity-backed: its
`X-User-ID` must be the id of a real `Employee` row, because ownership checks
compare the target resource's owning employee to `X-User-ID`. Never send a
placeholder id for the Employee role — always build its headers from the
employee resource returned by `POST /employees`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import ACCEPTING_ADMIN_USER_ID, INDEPENDENT_AUDITOR_USER_ID
from .types import (
    BENEFITS_ADMINISTRATOR,
    COMPLIANCE_AUDITOR,
    EMPLOYEE,
    PAYROLL_OPERATOR,
    RECORDKEEPER,
)

# Shared opaque-identity headers. `Employee` is present only as a template and
# MUST NOT be used for any request that touches an employee-owned resource.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "benefits_administrator": build_user_headers(
        ACCEPTING_ADMIN_USER_ID, BENEFITS_ADMINISTRATOR
    ),
    "payroll_operator": build_user_headers("payroll-1", PAYROLL_OPERATOR),
    "recordkeeper": build_user_headers("recordkeeper-1", RECORDKEEPER),
    "compliance_auditor": build_user_headers(
        INDEPENDENT_AUDITOR_USER_ID, COMPLIANCE_AUDITOR
    ),
}

ADMIN_HEADERS = TEST_USERS["benefits_administrator"]
PAYROLL_HEADERS = TEST_USERS["payroll_operator"]
RECORDKEEPER_HEADERS = TEST_USERS["recordkeeper"]
AUDITOR_HEADERS = TEST_USERS["compliance_auditor"]


def make_employee_headers(employee_id: str) -> Dict[str, str]:
    """
    Build headers for the entity-backed `Employee` role.

    `employee_id` must be the `id` of an existing Employee resource; ownership
    checks compare it directly to the resource's owning employee.
    """
    return build_user_headers(employee_id, EMPLOYEE)


def make_admin_headers(user_id: str = ACCEPTING_ADMIN_USER_ID) -> Dict[str, str]:
    """BenefitsAdministrator headers under a caller-chosen opaque user id."""
    return build_user_headers(user_id, BENEFITS_ADMINISTRATOR)


def make_auditor_headers(
    user_id: str = INDEPENDENT_AUDITOR_USER_ID,
) -> Dict[str, str]:
    """ComplianceAuditor headers under a caller-chosen opaque user id."""
    return build_user_headers(user_id, COMPLIANCE_AUDITOR)


def make_payroll_headers(user_id: str = "payroll-1") -> Dict[str, str]:
    """PayrollOperator headers under a caller-chosen opaque user id."""
    return build_user_headers(user_id, PAYROLL_OPERATOR)


def make_recordkeeper_headers(user_id: str = "recordkeeper-1") -> Dict[str, str]:
    """Recordkeeper headers under a caller-chosen opaque user id."""
    return build_user_headers(user_id, RECORDKEEPER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder for role/user-id combinations used by RBAC probes."""
    return build_user_headers(user_id, role)


# Headers with no identity at all, for the unauthenticated probe.
ANONYMOUS_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
