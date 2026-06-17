"""Auth header extraction and RBAC helpers (PRD §2.1, §2.6)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"OfficeManager", "Dispatcher", "Technician", "Customer"}


def authenticate():
    """Validate the X-User-ID / X-User-Role headers (PRD §2.1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise err(ERR_UNAUTHENTICATED, "Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unknown role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_UNAUTHORIZED if `role` is not in `allowed`."""
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED, "Role %s not permitted for this operation" % role)
