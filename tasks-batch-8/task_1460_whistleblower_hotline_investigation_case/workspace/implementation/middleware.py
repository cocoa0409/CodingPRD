"""Auth header extraction, role permission, and capability checks (PRD 2.1/2.11).

Priority order: (1) header presence + role validity -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER;
(2) role permitted for the endpoint -> ERR_INSUFFICIENT_PERMISSIONS;
(3) entity-backed roles resolve to an ACTIVE StaffMember carrying the matching
capability -> ERR_CAPABILITY_MISSING.
"""
from flask import request

from db import DB
from errors import ApiError

ROLES = [
    "HotlineReporter",
    "IntakeSpecialist",
    "Investigator",
    "ComplianceOfficer",
    "AuditCommitteeMember",
    "EthicsPlatformAdmin",
]

# Entity-backed roles: X-User-ID must resolve to a StaffMember with this capability.
ROLE_CAPABILITY = {
    "IntakeSpecialist": "INTAKE",
    "Investigator": "INVESTIGATION",
    "ComplianceOfficer": "OFFICER",
}

# Staff-facing read endpoints shared by the case-working roles.
STAFF_READ_ROLES = [
    "IntakeSpecialist",
    "Investigator",
    "ComplianceOfficer",
    "EthicsPlatformAdmin",
]


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; enforce endpoint role set + capability.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint"
        )
    if role in ROLE_CAPABILITY:
        staff = DB["staff_members"].get(user_id)
        if (
            staff is None
            or staff["employment_status"] != "ACTIVE"
            or ROLE_CAPABILITY[role] not in staff["capabilities"]
        ):
            raise ApiError(
                "ERR_CAPABILITY_MISSING",
                403,
                "Staff member is not ACTIVE or lacks the capability matching the role",
            )
    return user_id, role
