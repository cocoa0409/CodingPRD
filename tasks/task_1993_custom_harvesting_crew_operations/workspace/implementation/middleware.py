"""Auth header extraction and role checking (SCAFFOLD §1.4 / PRD §2.1)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

VALID_ROLES = {"HarvestOperator", "GrowerLiaison", "CrewBoss", "BillingClerk"}

# Read endpoints are shared by all four roles.
ALL_ROLES = frozenset(VALID_ROLES)


def get_auth_context():
    """Validate X-User-ID / X-User-Role headers.

    Returns (user_id, role) on success. Raises ApiError 400 when either
    header is missing or malformed (empty, or role not one of the four
    recognized role strings).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present",
        )
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing or malformed",
        )
    return user_id, role


def require_roles(*allowed_roles):
    """Validate headers and enforce role permission.

    Returns (user_id, role). Raises 400 for missing/malformed headers,
    403 for a recognized role that is not permitted to perform this op.
    """
    user_id, role = get_auth_context()
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role not permitted to perform this operation",
        )
    return user_id, role
