"""Auth middleware and helpers."""
from flask import request
from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, raise_error


VALID_ROLES = {"Customer", "ServicePersonnel", "PlatformOperator", "system"}


def get_caller():
    """Return (role, user_id). Validates X-User-Role presence and value.

    Raises ERR_UNAUTHENTICATED when header is missing or unknown.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header")
    return role, user_id


def require_roles(allowed_roles):
    """Check request role is in allowed_roles; raises ERR_FORBIDDEN otherwise.

    Returns (role, user_id).
    """
    role, user_id = get_caller()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"Role {role} is not permitted for this endpoint")
    return role, user_id


def get_caller_optional():
    """For internal sweep/clock endpoints: header presence is optional but role
    restrictions still apply when one is supplied.
    Returns (role or None, user_id or None).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role and role not in VALID_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Invalid X-User-Role header")
    return role, user_id


def require_roles_optional(allowed_roles):
    """For sweep endpoints: if X-User-Role provided, must be in allowed_roles.
    If omitted, allow through (acts as 'system')."""
    role, user_id = get_caller_optional()
    if role is not None and role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"Role {role} is not permitted for this endpoint")
    return role, user_id
