"""Auth header extraction and role checking per scaffold validations priority 1-2."""

from flask import request
from errors import unauthenticated, forbidden

ROLES = {"Student", "ProgramCoordinator", "FacultyApprover", "SafetyOfficer", "BursarOffice"}

# Staff roles that may use the clock endpoint
STAFF_ROLES = {"ProgramCoordinator", "FacultyApprover", "SafetyOfficer", "BursarOffice"}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated("X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise unauthenticated("X-User-Role is not a recognized role")
    return user_id, role


def require_role(role, allowed_roles):
    if role not in allowed_roles:
        raise forbidden("Role not permitted on this endpoint")


def check_student_ownership(user_id, role, resource_student_id):
    """For Student-role calls on student-scoped resources, linked student_id must equal X-User-ID."""
    if role == "Student" and resource_student_id != user_id:
        raise forbidden("Student may only access own resources")
