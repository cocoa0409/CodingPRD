"""Pre-built role headers for every role in the PRD.

PayrollAdmin and Supervisor carry OPAQUE operator identifiers (PRD §2.1): the
X-User-ID is recorded but never compared to any entity's id. Employee is
ENTITY-BACKED: its X-User-ID must be the acting Employee record's id, so an
employee header MUST be built per-instance via make_employee_headers(employee_id).

Distinct supervisor identities (sup-1 / sup-2 / sup-9) exist because segregation
of duties compares the submitter, the approver, and every punch editor by their
X-User-ID; tests need to control which supervisor acts.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Employee ownership.
TEST_USERS = {
    "payroll_admin_headers": build_user_headers("admin-1", "PayrollAdmin"),
    # Default supervisor (the "submitter" identity in most fixtures).
    "supervisor_headers": build_user_headers("sup-1", "Supervisor"),
    # A second, distinct supervisor for the approver/rejecter role.
    "supervisor2_headers": build_user_headers("sup-2", "Supervisor"),
    # A third supervisor used as a punch editor in segregation-of-duties tests.
    "supervisor_editor_headers": build_user_headers("sup-9", "Supervisor"),
    # Opaque Employee fallback — used ONLY for non-ownership tests (e.g. 403/404).
    "employee_headers": build_user_headers("employee-unbound", "Employee"),
}


def make_payroll_admin_headers(user_id: str = "admin-1") -> dict:
    """PayrollAdmin (opaque). user_id is recorded but never identity-checked."""
    return build_user_headers(user_id, "PayrollAdmin")


def make_supervisor_headers(user_id: str = "sup-1") -> dict:
    """Supervisor (opaque). Pass a distinct user_id to drive segregation of duties."""
    return build_user_headers(user_id, "Supervisor")


def make_employee_headers(user_id: str) -> dict:
    """Employee (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated (punch open/close, own break/tip)."""
    return build_user_headers(user_id, "Employee")
