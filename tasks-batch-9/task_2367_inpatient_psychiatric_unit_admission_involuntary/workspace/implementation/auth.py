"""Authentication and role authorization (PRD §2.1).

Headers: X-User-ID (acting user) and X-User-Role (acting capacity).
"""

from flask import request

from errors import fail

COMPLIANCE_OFFICER = "ComplianceOfficer"
INTAKE_CLINICIAN = "IntakeClinician"
ATTENDING_PSYCHIATRIST = "AttendingPsychiatrist"
CHARGE_NURSE = "ChargeNurse"
RIGHTS_ADVOCATE_ROLE = "PatientRightsAdvocate"

ALL_ROLES = (
    COMPLIANCE_OFFICER,
    INTAKE_CLINICIAN,
    ATTENDING_PSYCHIATRIST,
    CHARGE_NURSE,
    RIGHTS_ADVOCATE_ROLE,
)
ANY_ROLE = ALL_ROLES


def context(allowed_roles):
    """Validate auth headers then role authorization. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", f"role {role} may not perform this operation")
    return user_id, role
