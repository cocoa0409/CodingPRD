from flask import request

from errors import raise_err


def authenticate(allowed_roles):
    """Priority 1-2: context headers, then role authorization.

    Returns (user_id, role). Any authenticated role may be checked by passing
    the full role list.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise_err(
            "ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and must be non-empty",
        )
    if role not in allowed_roles:
        raise_err(
            "ERR_FORBIDDEN_ROLE",
            f"Role {role} is not authorized for this endpoint",
        )
    return user_id, role
