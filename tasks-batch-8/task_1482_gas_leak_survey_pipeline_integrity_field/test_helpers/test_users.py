"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are entity-backed identities: X-User-ID must be the id of a
persisted record of that role's entity type whenever the call is
ownership-gated. Use the make_*_headers builders with the created record's id.
The shared TEST_USERS constants are safe only for calls whose success does not
depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

# Bootstrap identity: the first IntegrityAnalyst record must be creatable
# before any record exists (no self-registration for later personnel).
BOOTSTRAP_ANALYST_ID = "bootstrap-integrity-analyst"

TEST_USERS = {
    "integrity_analyst_headers": build_user_headers(BOOTSTRAP_ANALYST_ID, "IntegrityAnalyst"),
    "field_technician_headers": build_user_headers("test-field-technician-1", "FieldTechnician"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "dispatch_coordinator_headers": build_user_headers("test-dispatch-coordinator-1", "DispatchCoordinator"),
    "calibration_tech_headers": build_user_headers("test-calibration-tech-1", "CalibrationTech"),
}


def make_integrity_analyst_headers(user_id: str) -> dict:
    """For IntegrityAnalyst (entity_backed). Pass the actual record id."""
    return build_user_headers(user_id, "IntegrityAnalyst")


def make_field_technician_headers(user_id: str) -> dict:
    """For FieldTechnician (entity_backed). Pass the actual record id."""
    return build_user_headers(user_id, "FieldTechnician")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (entity_backed). Pass the actual record id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_dispatch_coordinator_headers(user_id: str) -> dict:
    """For DispatchCoordinator (entity_backed). Pass the actual record id."""
    return build_user_headers(user_id, "DispatchCoordinator")


def make_calibration_tech_headers(user_id: str) -> dict:
    """For CalibrationTech (entity_backed). Pass the actual record id."""
    return build_user_headers(user_id, "CalibrationTech")
