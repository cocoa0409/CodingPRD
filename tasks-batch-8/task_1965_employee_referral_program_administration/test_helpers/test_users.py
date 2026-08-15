"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "talent_admin_headers": build_user_headers("ta-1", "TalentAdmin"),
    "recruiter_headers": build_user_headers("test-recruiter-1", "Recruiter"),
    "hiring_manager_headers": build_user_headers("test-hm-1", "HiringManager"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "payroll_processor_headers": build_user_headers("pp-1", "PayrollProcessor"),
    "compliance_officer_headers": build_user_headers("co-9", "ComplianceOfficer"),
}


def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Employee")


def make_recruiter_headers(user_id: str) -> dict:
    """For Recruiter (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Recruiter")


def make_hiring_manager_headers(user_id: str) -> dict:
    """For HiringManager (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "HiringManager")
