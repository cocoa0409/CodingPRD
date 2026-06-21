"""Pre-built role headers for every role in the PRD (Section 2.1).

HrAdmin is an opaque operator identity (X-User-ID not tied to any entity),
so its shared constant is canonical. Manager / Employee / HrbpPartner /
CompApprover are entity_backed:Employee — ownership and segregation-of-duties
checks compare X-User-ID to an Employee.id, so those calls MUST use the
per-instance builder with the actual Employee id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque HrAdmin role, and for tests that do
# not exercise ownership / segregation-of-duties (e.g. 401/403/404 checks).
TEST_USERS = {
    "hr_admin_headers": build_user_headers("test-hradmin-1", "HrAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "hrbp_headers": build_user_headers("test-hrbp-1", "HrbpPartner"),
    "comp_approver_headers": build_user_headers("test-approver-1", "CompApprover"),
}


# Per-instance builders — required for every entity_backed:Employee role.
# Pass the acting Employee.id whenever the call is ownership- or SoD-gated.
def make_manager_headers(user_id: str) -> dict:
    """Manager acting as the Employee whose id is user_id (the reviewer)."""
    return build_user_headers(user_id, "Manager")


def make_employee_headers(user_id: str) -> dict:
    """Employee acting as the Employee whose id is user_id (the review subject / rater)."""
    return build_user_headers(user_id, "Employee")


def make_hrbp_headers(user_id: str) -> dict:
    """HrbpPartner acting as the Employee whose id is user_id (the facilitator)."""
    return build_user_headers(user_id, "HrbpPartner")


def make_comp_approver_headers(user_id: str) -> dict:
    """CompApprover acting as the Employee whose id is user_id (the approver)."""
    return build_user_headers(user_id, "CompApprover")
