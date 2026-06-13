"""Auth header extraction and RBAC (PRD §2.1, §2.9).

Headers: X-User-ID (acting user id) and X-User-Role (capacity).
Roles: StudioManager, Artist, Client, Anonymous.

Validation precedence (PRD §2.9):
  1. ERR_UNAUTHENTICATED (401) — missing/invalid headers on a protected endpoint
  2. ERR_FORBIDDEN (403)       — present but unpermitted role
"""
from functools import wraps

from flask import request

from errors import ApiError

VALID_ROLES = {"StudioManager", "Artist", "Client"}


def get_identity():
    """Return (user_id, user_role) from headers (may be None)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_ownership(expected_id):
    """Entity-backed ownership check (PRD §2.1).

    When the acting role is entity-backed (Artist or Client), its X-User-ID is
    the id of the acting entity; ownership checks compare the resource's
    relevant foreign key (expected_id) to X-User-ID. A mismatch is ERR_FORBIDDEN.
    StudioManager (opaque identity) is not subject to ownership comparison.

    This must be called AFTER existence resolution so a missing resource still
    surfaces ERR_NOT_FOUND first (PRD §2.9 precedence).
    """
    user_id, user_role = get_identity()
    if user_role == "StudioManager":
        return
    if user_id != expected_id:
        raise ApiError("ERR_FORBIDDEN",
                       "Acting user does not own this resource")


def require_auth(allowed_roles):
    """Decorator enforcing authentication then role authorization.

    allowed_roles: iterable of role names permitted for this operation.
    The headers must be present and the role must be one of the recognized
    roles; then the role must be in allowed_roles.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_identity()
            # Authentication: both headers present and role recognized.
            if not user_id or not user_role or user_role not in VALID_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED",
                               "Missing or invalid authentication headers")
            # Authorization: role permitted for this operation.
            if user_role not in allowed:
                raise ApiError("ERR_FORBIDDEN",
                               "Role %s is not permitted for this operation" % user_role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
