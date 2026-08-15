"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (SystemAdmin, IntakeCoordinator, ComplianceAuditor) use shared
constants. Entity-backed roles (PatientAdvocate, DepartmentInvestigator,
QualityRiskOfficer, PatientRelationsDirector) MUST be built per-instance with
the acting StaffMember's id via the make_*_headers builders — ownership and
capability checks compare X-User-ID against persisted staff records.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that never exercise
# entity-backed ownership/capability checks.
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
    "intake_coordinator_headers": build_user_headers(
        "test-intake-coordinator-1", "IntakeCoordinator"),
    "compliance_auditor_headers": build_user_headers(
        "test-compliance-auditor-1", "ComplianceAuditor"),
}


def make_advocate_headers(staff_id: str) -> dict:
    """PatientAdvocate is entity-backed: X-User-ID must be the StaffMember id."""
    return build_user_headers(staff_id, "PatientAdvocate")


def make_investigator_headers(staff_id: str) -> dict:
    """DepartmentInvestigator is entity-backed: X-User-ID must be the StaffMember id."""
    return build_user_headers(staff_id, "DepartmentInvestigator")


def make_qro_headers(staff_id: str) -> dict:
    """QualityRiskOfficer is entity-backed: X-User-ID must be the StaffMember id."""
    return build_user_headers(staff_id, "QualityRiskOfficer")


def make_director_headers(staff_id: str) -> dict:
    """PatientRelationsDirector is entity-backed: X-User-ID must be the StaffMember id."""
    return build_user_headers(staff_id, "PatientRelationsDirector")
