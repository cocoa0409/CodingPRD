"""Authentication and authorisation (PRD §2.1, order-of-rejection checks 1-2)."""
from flask import request

from constants import ALL_ROLES
from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, fail


def authenticate(allowed_roles):
    """Check 1 then check 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        fail(ERR_UNAUTHENTICATED,
             "X-User-ID and X-User-Role headers are required and the role must "
             "be one of the five declared roles.")
    if role not in allowed_roles:
        fail(ERR_UNAUTHORIZED,
             "Role %s is not authorised for this operation." % role)
    return user_id, role


def any_role():
    return ALL_ROLES
