"""Auth header extraction and role checking."""
from flask import request

import errors
from errors import ApiError

KNOWN_ROLES = {"ClubAdmin", "Member", "RegisterClerk", "ServiceDeskClerk", "Anonymous"}


def get_user_context(anonymous_allowed=False):
    """Validate X-User-ID and X-User-Role headers.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401) if
    either header is missing or X-User-Role is not a known role.

    anonymous_allowed only relaxes the *role authorization* later, not the header
    presence requirement — but signup may be called without authenticating at all,
    so when anonymous_allowed and no headers present, returns (None, 'Anonymous').
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if anonymous_allowed and user_id is None and role is None:
        # Unauthenticated signup is permitted.
        return None, "Anonymous"

    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
            401,
            "Missing or invalid user context.",
        )
    return user_id, role


def require_roles(role, allowed_roles):
    if role not in allowed_roles:
        raise ApiError(
            errors.ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role not permitted for this operation.",
        )
