"""Authentication, role authorisation and acting-staff resolution.

Implements validation ladder rungs 1 (ERR_UNAUTHENTICATED), 2
(ERR_ROLE_NOT_PERMITTED) and 3 (ERR_STAFF_IDENTITY_MISMATCH).
"""
from flask import request

from errors import ApiError
from store import db

LAB_MANAGER = "LabManager"
TECHNOLOGIST = "Technologist"
ORDERING_PHYSICIAN = "OrderingPhysician"
INTERPRETING_PHYSICIAN = "InterpretingPhysician"
COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = [LAB_MANAGER, TECHNOLOGIST, ORDERING_PHYSICIAN,
             INTERPRETING_PHYSICIAN, COMPLIANCE_AUDITOR]

# The three roles that are backed by a Staff record.
ROLE_TO_ROLE_TYPE = {
    TECHNOLOGIST: "TECHNOLOGIST",
    ORDERING_PHYSICIAN: "ORDERING_PHYSICIAN",
    INTERPRETING_PHYSICIAN: "INTERPRETING_PHYSICIAN",
}


class Actor(object):
    __slots__ = ("user_id", "role", "staff")

    def __init__(self, user_id, role, staff):
        self.user_id = user_id
        self.role = role
        self.staff = staff

    @property
    def staff_id(self):
        return self.staff["id"] if self.staff else None


def authenticate(allowed_roles):
    """Run the three authorisation rungs and return the acting Actor."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role header is required.")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role is not a recognised role.")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Role %s may not perform this operation." % role)
    staff = None
    expected_type = ROLE_TO_ROLE_TYPE.get(role)
    if expected_type is not None:
        record = db.staff.get(user_id)
        if record is None or record.get("role_type") != expected_type:
            raise ApiError(
                "ERR_STAFF_IDENTITY_MISMATCH",
                "X-User-ID does not resolve to a %s staff record." % role)
        staff = record
    return Actor(user_id, role, staff)
