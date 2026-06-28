"""Pre-built role headers for every role in the PRD (PRD 2.1).

ProgramManager and GivingAdmin are opaque operator identities — X-User-ID is not compared
to any entity. Employee is entity_backed: X-User-ID must equal the acting Employee.id for
ownership-gated operations, so every Employee-acted call must use make_employee_headers(emp_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
    "giving_admin_headers": build_user_headers("test-admin-1", "GivingAdmin"),
    # Employee is entity_backed: this shared constant is only a fallback for non-ownership
    # tests (e.g. forbidden-role checks). Ownership-gated calls MUST use make_employee_headers.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_program_manager_headers() -> dict:
    return TEST_USERS["program_manager_headers"]


def make_giving_admin_headers() -> dict:
    return TEST_USERS["giving_admin_headers"]


def make_employee_headers(user_id: str) -> dict:
    """For the Employee role (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated (donation cancel, schedule pause/resume/cancel)."""
    return build_user_headers(user_id, "Employee")
