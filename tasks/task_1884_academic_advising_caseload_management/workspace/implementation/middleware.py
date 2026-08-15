"""Auth header extraction and role checking, per scaffold validations priority 1 and 3."""
from flask import request

import errors
from errors import ApiError

ROLES = ("AdvisingDirector", "Advisor", "FrontDeskStaff", "FacultyReferrer")


def get_auth_context():
    """Validate X-User-ID and X-User-Role headers. Raises ApiError on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be one of the declared roles",
            400,
        )
    return user_id, role


def require_role(role, allowed_roles):
    """Check the caller's role is in the endpoint's roles list."""
    if role not in allowed_roles:
        raise ApiError(
            errors.ERR_UNAUTHORIZED_ROLE,
            f"Role {role} is not authorized for this endpoint",
            403,
        )
