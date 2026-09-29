"""Authentication / RBAC (PRD 2.1, validation priorities 1 and 2)."""

from flask import g, request

from db import db
from errors import ApiError

# Declared API roles.  A value of None means the role is opaque (no StaffMember
# row backs it); otherwise the caller's X-User-ID must be an active StaffMember
# whose staff_role equals the mapped value.  SURGEON is a credentialed duty and
# is deliberately NOT an API role.
ROLE_STAFF_ROLE = {
    "ProgramAdmin": None,
    "FinanceAdmin": None,
    "TransplantCoordinator": "TRANSPLANT_COORDINATOR",
    "DonorAdvocate": "LIVING_DONOR_ADVOCATE",
    "EvaluationReviewer": "EVALUATION_REVIEWER",
    "QualityOfficer": "QUALITY_OFFICER",
}

ALL_ROLES = (
    "ProgramAdmin",
    "TransplantCoordinator",
    "DonorAdvocate",
    "EvaluationReviewer",
    "QualityOfficer",
    "FinanceAdmin",
)


def authenticate(allowed_roles):
    """Priority 1 then priority 2.  Populates g.user_id / g.role / g.staff."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip() or role is None or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    user_id = str(user_id).strip()
    role = str(role).strip()

    if role not in ROLE_STAFF_ROLE or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)

    staff = None
    required_staff_role = ROLE_STAFF_ROLE[role]
    if required_staff_role is not None:
        staff = db.staff_members.get(user_id)
        if staff is None or not staff["is_active"] or staff["staff_role"] != required_staff_role:
            raise ApiError(
                "ERR_UNAUTHORIZED",
                "X-User-ID is not an active %s" % required_staff_role,
            )

    g.user_id = user_id
    g.role = role
    g.staff = staff
    return staff
