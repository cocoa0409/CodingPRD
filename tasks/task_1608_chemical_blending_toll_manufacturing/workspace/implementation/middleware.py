"""Auth header extraction and role checking."""
from flask import request

import errors


VALID_ROLES = {
    "QualityManager",
    "BatchScheduler",
    "TankOperator",
    "QAValidator",
    "SDSAuthor",
    "ShippingClerk",
}


def get_auth():
    """Returns (user_id, role) or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID header missing or malformed",
        )
    if not role or not isinstance(role, str) or not role.strip():
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header missing or malformed",
        )
    if role not in VALID_ROLES:
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role not a recognized role",
        )
    return user_id, role


def require_role(allowed_roles):
    """allowed_roles: set of role names, or {'Any'} for any authenticated role."""
    user_id, role = get_auth()
    if "Any" in allowed_roles:
        return user_id, role
    if role not in allowed_roles:
        raise errors.ApiError(
            errors.ERR_UNAUTHORIZED,
            403,
            f"Role {role} not permitted for this endpoint",
        )
    return user_id, role
