"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.9)."""
from flask import request

from errors import err

ROLES = {"ShopAdmin", "Estimator", "Scheduler", "MaterialController", "Inspector"}


def get_identity():
    """Return (user_id, role). Both headers must be present and non-empty,
    else ERR_UNAUTHENTICATED. Required on every write (and we call it on
    reads too, since reads also require authentication per §2.9 — any
    authenticated role may read)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_auth():
    """Authentication only (any role). Used for GET reads."""
    get_identity()


def require_roles(*allowed):
    """Authenticate, then authorize the acting role against the allowed set."""
    _, role = get_identity()
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role '%s' is not permitted for this operation" % role)
    return role
