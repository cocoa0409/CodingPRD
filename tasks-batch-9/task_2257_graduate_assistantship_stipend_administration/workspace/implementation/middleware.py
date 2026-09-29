"""Authentication / authorisation (PRD 2.1, validation priorities 1-3)."""
from flask import request

from errors import ApiError

ROLES = (
    "GradSchoolAdmin",
    "DepartmentAdmin",
    "GrantAccountant",
    "FacultySupervisor",
    "StudentUser",
)

ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Priority 1 (401) then priority 2 (403).  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not permitted for this operation" % role,
        )
    return user_id, role


def require_owner(actor_id, role, owner_student_id):
    """Priority 3: a StudentUser may only address its own records."""
    if role == "StudentUser" and actor_id != owner_student_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "A StudentUser may only address its own records",
        )
