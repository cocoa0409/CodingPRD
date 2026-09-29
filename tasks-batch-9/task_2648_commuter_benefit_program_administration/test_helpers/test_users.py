"""Role headers for the Commuter Benefit Program Administration API.

Four of the five roles carry an opaque operator identifier in ``X-User-ID``; the
``Employee`` role carries the id of the acting Employee row, so an Employee
header can only be built once the employee exists.  Two workflows compare two
opaque operator ids against each other (batch release against
``sealed_by_user_id``, transaction reopen against ``approved_by_user_id``), so
per-instance builders are provided for every role and must be used wherever the
identity of the actor is load-bearing.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_EMPLOYEE = "Employee"
ROLE_ORDER_DESK = "OrderDesk"
ROLE_COMPLIANCE_REVIEWER = "ComplianceReviewer"
ROLE_PAYROLL_PROCESSOR = "PayrollProcessor"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_EMPLOYEE,
    ROLE_ORDER_DESK,
    ROLE_COMPLIANCE_REVIEWER,
    ROLE_PAYROLL_PROCESSOR,
]

# --- Shared constants: safe for any call that is not identity-sensitive --------
TEST_USERS = {
    ROLE_PROGRAM_ADMIN: build_user_headers("admin-default", ROLE_PROGRAM_ADMIN),
    ROLE_ORDER_DESK: build_user_headers("desk-default", ROLE_ORDER_DESK),
    ROLE_COMPLIANCE_REVIEWER: build_user_headers(
        "reviewer-default", ROLE_COMPLIANCE_REVIEWER
    ),
    ROLE_PAYROLL_PROCESSOR: build_user_headers(
        "payroll-default", ROLE_PAYROLL_PROCESSOR
    ),
}

PROGRAM_ADMIN = TEST_USERS[ROLE_PROGRAM_ADMIN]
ORDER_DESK = TEST_USERS[ROLE_ORDER_DESK]
COMPLIANCE_REVIEWER = TEST_USERS[ROLE_COMPLIANCE_REVIEWER]
PAYROLL_PROCESSOR = TEST_USERS[ROLE_PAYROLL_PROCESSOR]


# --- Per-instance builders ----------------------------------------------------
def make_program_admin_headers(user_id: str = "admin-default") -> dict:
    """Headers for a ProgramAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_order_desk_headers(user_id: str) -> dict:
    """Headers for an OrderDesk operator.

    The identifier is persisted as ``sealed_by_user_id`` / ``released_by_user_id``
    and is compared for the release segregation-of-duties gate, so every
    procurement call must name its operator explicitly.
    """
    return build_user_headers(user_id, ROLE_ORDER_DESK)


def make_compliance_reviewer_headers(user_id: str) -> dict:
    """Headers for a ComplianceReviewer.

    The identifier is persisted as ``reviewed_by_user_id`` on a claim and as
    ``approved_by_user_id`` / ``denied_by_user_id`` on the underlying card
    transaction, and the reopen gate compares it against ``approved_by_user_id``.
    """
    return build_user_headers(user_id, ROLE_COMPLIANCE_REVIEWER)


def make_payroll_processor_headers(user_id: str = "payroll-default") -> dict:
    """Headers for a PayrollProcessor acting under a specific operator id."""
    return build_user_headers(user_id, ROLE_PAYROLL_PROCESSOR)


def make_employee_headers(user_id: str) -> dict:
    """Headers for the Employee whose row id is ``user_id``.

    ``Employee`` is the one entity-backed role: ownership checks compare the
    target resource's owning employee to this value, so the caller must thread
    the real Employee id through.  There is deliberately no shared Employee
    constant.
    """
    return build_user_headers(user_id, ROLE_EMPLOYEE)


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder used by role-matrix tests."""
    return build_user_headers(user_id, role)
