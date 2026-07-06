"""Authentication & RBAC (PRD §2.1, §2.7; SCAFFOLD validations priority 1-2).

Headers: X-User-ID identifies the acting user; X-User-Role declares the role.
Recognized roles: PlatformAdmin, VenueOperator, GateAttendant, Patron.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

RECOGNIZED_ROLES = {"PlatformAdmin", "VenueOperator", "GateAttendant", "Patron"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    Missing X-User-ID/X-User-Role, or an unrecognized role -> 401 (PRD §2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unrecognized auth headers.")
    return user_id, role


def require_role(role, allowed):
    """Endpoint-level authorization (PRD §2.7): role must be in `allowed`.

    Raises ERR_UNAUTHORIZED (403) otherwise.
    """
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED, "Role %s may not perform this operation." % role)
