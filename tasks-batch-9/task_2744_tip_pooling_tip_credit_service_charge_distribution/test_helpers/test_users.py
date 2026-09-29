"""Pre-built role headers for every role in the PRD.

``PayrollAdmin``, ``PayrollPreparer`` and ``ComplianceOfficer`` are opaque
operator identities: the shared constants below are their canonical form.
``ShiftManager`` and ``Employee`` act as the Employee row named by
``X-User-ID``, so every ownership-gated call must use the per-instance builders
with the real ``Employee.id``.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct operator identities. Segregation of duties compares the acting
# X-User-ID against the recorded computed_by_user_id / issued_by_user_id, so the
# suite needs more than one identity per operator role.
PAYROLL_ADMIN_USER_ID = "op_admin_1"
PAYROLL_PREPARER_USER_ID = "op_prep_1"
PAYROLL_PREPARER_ALT_USER_ID = "op_prep_2"
COMPLIANCE_OFFICER_USER_ID = "op_comp_1"
COMPLIANCE_OFFICER_ALT_USER_ID = "op_comp_2"

TEST_USERS = {
    # opaque roles — shared constants are the canonical form
    "payroll_admin_headers": build_user_headers(PAYROLL_ADMIN_USER_ID, "PayrollAdmin"),
    "payroll_preparer_headers": build_user_headers(
        PAYROLL_PREPARER_USER_ID, "PayrollPreparer"
    ),
    "payroll_preparer_alt_headers": build_user_headers(
        PAYROLL_PREPARER_ALT_USER_ID, "PayrollPreparer"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_alt_headers": build_user_headers(
        COMPLIANCE_OFFICER_ALT_USER_ID, "ComplianceOfficer"
    ),
    # entity_backed roles — fallback for tests that never touch ownership
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "shift_manager_headers": build_user_headers("test-shift-manager-1", "ShiftManager"),
}


def make_employee_headers(employee_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the real Employee.id."""
    return build_user_headers(employee_id, "Employee")


def make_shift_manager_headers(employee_id: str) -> dict:
    """For ShiftManager (entity_backed:Employee). Pass the real Employee.id."""
    return build_user_headers(employee_id, "ShiftManager")


def make_payroll_admin_headers(user_id: str = PAYROLL_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PayrollAdmin")


def make_payroll_preparer_headers(user_id: str = PAYROLL_PREPARER_USER_ID) -> dict:
    return build_user_headers(user_id, "PayrollPreparer")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
