"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.9, §1.7)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"Anonymous", "Customer", "WarehouseOperator", "StoreAdmin"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def get_auth_optional():
    """Return (user_id, role) without raising; for exempt endpoints that may
    still want to know the caller. Either value may be None/unknown."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_roles(allowed):
    """Authenticate and enforce that the caller's role is in `allowed`.

    Returns (user_id, role). Auth (401) is checked before role (403),
    matching the validation priority order in PRD §2.9.
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role '%s' is not permitted for this operation" % role)
    return user_id, role
