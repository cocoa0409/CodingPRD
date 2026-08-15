"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# Employee ownership. Named officer ids support segregation-of-duties scenarios.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "ComplianceAdmin"),
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "officer2_headers": build_user_headers("officer-2", "ComplianceOfficer"),
    "officer3_headers": build_user_headers("officer-3", "ComplianceOfficer"),
    "hr_headers": build_user_headers("hr-1", "HRPartner"),
    "auditor_headers": build_user_headers("auditor-1", "ExternalAuditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """ComplianceAdmin (opaque identity)."""
    return build_user_headers(user_id, "ComplianceAdmin")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """ComplianceOfficer (opaque identity). Pass distinct ids for SoD pairs."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_hr_headers(user_id: str = "hr-1") -> dict:
    """HRPartner (opaque identity)."""
    return build_user_headers(user_id, "HRPartner")


def make_auditor_headers(user_id: str = "auditor-1") -> dict:
    """ExternalAuditor (opaque identity)."""
    return build_user_headers(user_id, "ExternalAuditor")


def make_employee_headers(user_id: str) -> dict:
    """Employee (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated (own licenses only)."""
    return build_user_headers(user_id, "Employee")
