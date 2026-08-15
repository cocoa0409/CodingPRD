"""Pre-built role headers for every role in the PRD (§2.1).

Two kinds of entries:
- Shared constants in TEST_USERS for opaque-identity roles (HRAdmin,
  FinanceAdmin, PayrollSpecialist, VendorOps), whose X-User-ID is never
  compared to any entity id.
- Per-instance builders make_manager_headers / make_employee_headers for the
  entity-backed roles (Manager, Employee), whose X-User-ID MUST be the id of
  the acting Employee whenever the call is ownership- or scope-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "hr_admin_headers": build_user_headers("hr-admin-1", "HRAdmin"),
    "finance_admin_headers": build_user_headers("finance-admin-1", "FinanceAdmin"),
    "payroll_specialist_headers": build_user_headers("payroll-specialist-1", "PayrollSpecialist"),
    "vendor_ops_headers": build_user_headers("vendor-ops-1", "VendorOps"),
    # Entity-backed roles: fallback constants ONLY for tests that do not
    # exercise ownership/scope (e.g. RBAC denial where a non-owning Employee
    # identity is exactly what the test wants).
    "manager_headers": build_user_headers("manager-generic-1", "Manager"),
    "employee_headers": build_user_headers("employee-generic-1", "Employee"),
}


def make_manager_headers(user_id: str) -> dict:
    """Manager is entity-backed: X-User-ID must be the acting Employee.id
    whenever the call is ownership- or manager-chain-scope-gated."""
    return build_user_headers(user_id, "Manager")


def make_employee_headers(user_id: str) -> dict:
    """Employee is entity-backed: X-User-ID must be the acting Employee.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Employee")
