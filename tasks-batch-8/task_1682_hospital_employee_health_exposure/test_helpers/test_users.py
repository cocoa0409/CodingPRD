"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for tests that do not
# exercise ownership. For the entity-backed StaffEmployee role, prefer
# make_staff_employee_headers(employee_id) on any ownership-gated call.
TEST_USERS = {
    "nurse_headers": build_user_headers("ehn-1", "EmployeeHealthNurse"),
    "physician_headers": build_user_headers("ehp-1", "EmployeeHealthPhysician"),
    "compliance_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "safety_headers": build_user_headers("so-1", "SafetyOfficer"),
    # Fallback for StaffEmployee calls that are not ownership-gated.
    "staff_headers": build_user_headers("staff-1", "StaffEmployee"),
}


def make_nurse_headers(user_id: str) -> dict:
    """Nurse headers with a specific operator id (opaque role; used where the
    audit trail or segregation-of-duties check compares X-User-ID values,
    e.g. exposure intake vs source-consent recording)."""
    return build_user_headers(user_id, "EmployeeHealthNurse")


def make_physician_headers(user_id: str) -> dict:
    """Physician headers with a specific operator id (opaque role)."""
    return build_user_headers(user_id, "EmployeeHealthPhysician")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a specific operator id (opaque role)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_safety_headers(user_id: str) -> dict:
    """SafetyOfficer headers with a specific operator id (opaque role)."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_staff_employee_headers(user_id: str) -> dict:
    """For StaffEmployee (entity-backed: the X-User-ID IS the Employee id).
    Pass the actual Employee.id whenever the call is ownership-gated (PEP
    declination, participation declination, symptom reports, self reads)."""
    return build_user_headers(user_id, "StaffEmployee")
