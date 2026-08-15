"""Pre-built role headers for every role in the PRD.

ComplianceAdmin / HRAdmin / Auditor / Anonymous use opaque operator ids, so a
shared constant header set is canonical. Manager and Employee are backed by
Employee records: for any ownership-gated call, build headers with the actual
employee id via make_manager_headers(employee_id) / make_employee_headers(employee_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "compliance_admin_headers": build_user_headers("op-compliance-admin-1", "ComplianceAdmin"),
    "hr_admin_headers": build_user_headers("op-hr-admin-1", "HRAdmin"),
    "auditor_headers": build_user_headers("op-auditor-1", "Auditor"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Fallbacks for entity-backed roles in tests that never exercise ownership
    # (e.g., role-denied checks where the role gate fires first).
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_manager_headers(user_id: str) -> dict:
    """Manager is entity-backed: pass the acting manager's Employee.id."""
    return build_user_headers(user_id, "Manager")


def make_employee_headers(user_id: str) -> dict:
    """Employee is entity-backed: pass the acting employee's Employee.id."""
    return build_user_headers(user_id, "Employee")
