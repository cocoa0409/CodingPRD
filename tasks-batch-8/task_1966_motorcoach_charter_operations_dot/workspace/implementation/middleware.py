"""Auth middleware and role checking."""

from flask import request

import errors


VALID_ROLES = {
    "PlatformAdmin",
    "QuoteAgent",
    "DispatchManager",
    "FleetManager",
    "SafetyOfficer",
    "ComplianceOfficer",
    "Customer",
}


def get_auth():
    """Returns (user_id, role) after validating headers. Raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.make_error(
            errors.ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-Role or X-User-ID header",
        )
    return user_id, role


def require_roles(*allowed_roles):
    """Validate auth and check that role is in allowed_roles. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise errors.make_error(
            errors.ERR_UNAUTHORIZED,
            f"Role {role} is not authorized for this endpoint",
        )
    return user_id, role
