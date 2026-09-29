"""Pre-built role headers for every role in the PRD.

Five of the six roles are backed by a StaffMember row: their X-User-ID is
compared against StaffMember.id by the segregation-of-duties and
case-attachment rules, so any ownership-gated call MUST use the
per-instance builder with the real StaffMember id.

PatientAccessCoordinator is the only role whose X-User-ID is an opaque
operator identifier that is never compared to an entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque role, and for tests whose outcome does
# not depend on the caller being a particular StaffMember (missing-header,
# wrong-role, unknown-id and payload-validation tests).
TEST_USERS = {
    "charge_nurse_headers": build_user_headers("test-charge-nurse-1", "ChargeNurse"),
    "bedside_nurse_headers": build_user_headers("test-bedside-nurse-1", "BedsideNurse"),
    "obstetrician_headers": build_user_headers(
        "test-obstetrician-1", "ObstetricianAttending"
    ),
    "anesthesia_lead_headers": build_user_headers("test-anesthesia-1", "AnesthesiaLead"),
    "safety_officer_headers": build_user_headers(
        "test-safety-officer-1", "PerinatalSafetyOfficer"
    ),
    "access_coordinator_headers": build_user_headers(
        "test-access-coordinator-1", "PatientAccessCoordinator"
    ),
}

ROLE_HEADER_KEYS = {
    "ChargeNurse": "charge_nurse_headers",
    "BedsideNurse": "bedside_nurse_headers",
    "ObstetricianAttending": "obstetrician_headers",
    "AnesthesiaLead": "anesthesia_lead_headers",
    "PerinatalSafetyOfficer": "safety_officer_headers",
    "PatientAccessCoordinator": "access_coordinator_headers",
}


def make_charge_nurse_headers(user_id: str) -> dict:
    """ChargeNurse acting as a specific StaffMember. Pass the StaffMember.id."""
    return build_user_headers(user_id, "ChargeNurse")


def make_bedside_nurse_headers(user_id: str) -> dict:
    """BedsideNurse acting as a specific StaffMember. Pass the StaffMember.id."""
    return build_user_headers(user_id, "BedsideNurse")


def make_obstetrician_headers(user_id: str) -> dict:
    """ObstetricianAttending acting as a specific StaffMember. Pass the StaffMember.id."""
    return build_user_headers(user_id, "ObstetricianAttending")


def make_anesthesia_lead_headers(user_id: str) -> dict:
    """AnesthesiaLead acting as a specific StaffMember. Pass the StaffMember.id."""
    return build_user_headers(user_id, "AnesthesiaLead")


def make_safety_officer_headers(user_id: str) -> dict:
    """PerinatalSafetyOfficer acting as a specific StaffMember. Pass the StaffMember.id."""
    return build_user_headers(user_id, "PerinatalSafetyOfficer")


def make_access_coordinator_headers(user_id: str = "test-access-coordinator-1") -> dict:
    """PatientAccessCoordinator. Its X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "PatientAccessCoordinator")


def headers_for_role(role: str, user_id: str) -> dict:
    """Build headers for any role name with an explicit acting identity."""
    return build_user_headers(user_id, role)
