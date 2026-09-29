"""Authentication and role-based access control (PRD 2.1, ladder bands 1-3)."""

from flask import request

from errors import api_error
from validation import ROLES

ANY = "ANY"


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise api_error("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        raise api_error("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    return str(user_id).strip(), str(role).strip()


def require_roles(allowed):
    """Band 1 then band 2 of the rejection ladder."""
    user_id, role = authenticate()
    if role not in ROLES:
        raise api_error("ERR_ROLE_NOT_PERMITTED", "unknown role '%s'" % role)
    if allowed != ANY and role not in allowed:
        raise api_error(
            "ERR_ROLE_NOT_PERMITTED", "role '%s' may not use this endpoint" % role
        )
    return user_id, role


def require_action_role(role, action, action_roles):
    """Band 3: the role must be permitted for the specific action value."""
    allowed = action_roles.get(action)
    if allowed is None:
        # Unknown action value: a request-shape failure.
        raise api_error(
            "ERR_INVALID_REQUEST", "unsupported action '%s'" % action
        )
    if role not in allowed:
        raise api_error(
            "ERR_ROLE_NOT_PERMITTED",
            "role '%s' may not perform action '%s'" % (role, action),
        )
