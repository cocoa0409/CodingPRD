"""Pre-built role headers for every role in the PRD.

PRD §2.1: when X-User-Role is Employee, X-User-ID is the id of the acting
Employee entity and ownership checks compare it to that id. For BenefitsAdmin,
ClaimsAdjuster, Payroll, and System, X-User-ID is an opaque operator identifier
not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Employee tests that do not
# exercise ownership (e.g. 400/404 paths). For ownership-gated Employee calls,
# use make_employee_headers(employee_id) below.
TEST_USERS = {
    "benefits_admin_headers": build_user_headers("admin-1", "BenefitsAdmin"),
    "claims_adjuster_headers": build_user_headers("adjuster-1", "ClaimsAdjuster"),
    "payroll_headers": build_user_headers("payroll-1", "Payroll"),
    "system_headers": build_user_headers("system-1", "System"),
    # Employee is entity_backed; this shared constant is a fallback for
    # non-ownership Employee tests only.
    "employee_headers": build_user_headers("employee-1", "Employee"),
}


def make_employee_headers(user_id: str) -> dict:
    """For the Employee role (entity_backed:Employee). Pass the actual
    Employee.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Employee")
