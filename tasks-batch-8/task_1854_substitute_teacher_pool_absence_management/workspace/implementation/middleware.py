"""Auth context extraction, role permission, and entity-backed ownership.

Headers: X-User-ID and X-User-Role. Five roles: DistrictAdmin,
SchoolCoordinator, Teacher, Substitute, PayrollClerk.
"""

from flask import request

import db
from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_AUTH_CONTEXT,
    ERR_FORBIDDEN_ROLE,
    ERR_RESOURCE_OWNERSHIP_VIOLATION,
)

ROLES = {"DistrictAdmin", "SchoolCoordinator", "Teacher", "Substitute", "PayrollClerk"}

ALL_ROLES = ["DistrictAdmin", "SchoolCoordinator", "Teacher", "Substitute", "PayrollClerk"]


def auth_context():
    """Pipeline stage 1: both headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_MISSING_OR_INVALID_AUTH_CONTEXT,
                  "X-User-ID and X-User-Role headers are required and role must be recognized")
    return user_id, role


def require_role(role, allowed):
    """Pipeline stage 3: role permitted for the endpoint."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this endpoint" % role)


def coordinator_staff(user_id):
    """Resolve the coordinator's StaffMember record (is_coordinator true).
    Returns the record or None; callers raise ownership violations."""
    staff = db.STORE.staff_members.get(user_id)
    if staff is None or not staff.get("is_coordinator"):
        return None
    return staff


def require_coordinator_school(user_id, school_id):
    """Pipeline stage 4: coordinator acts only within their own school.
    school_id None means 'cannot be determined' -> defer to existence stage."""
    if school_id is None:
        return
    staff = coordinator_staff(user_id)
    if staff is None or staff["school_id"] != school_id:
        raise_err(ERR_RESOURCE_OWNERSHIP_VIOLATION,
                  "Coordinator may act only on resources of their own school")


def require_teacher_self(user_id, staff_member_id):
    if staff_member_id != user_id:
        raise_err(ERR_RESOURCE_OWNERSHIP_VIOLATION,
                  "Teacher may act only on their own absences")


def require_substitute_self(user_id, substitute_id):
    if substitute_id is None:
        return
    if substitute_id != user_id:
        raise_err(ERR_RESOURCE_OWNERSHIP_VIOLATION,
                  "Substitute may act only on their own assignments and timesheets")
