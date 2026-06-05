"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.10)."""
from flask import request

from errors import err

ROLES = {"Requester", "Agent", "ChangeManager", "CabMember", "PlatformAdmin"}


def get_identity():
    """Return (user_id, user_role) from headers, or (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    return user_id, user_role


def require_auth(allowed_roles):
    """Enforce auth (401) then RBAC (403). Returns (user_id, user_role).

    Order is pinned by PRD §3.10: ERR_UNAUTHENTICATED precedes ERR_FORBIDDEN.
    """
    user_id, user_role = get_identity()
    if not user_id or not user_role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if allowed_roles is not None and user_role not in allowed_roles:
        raise err(
            "ERR_FORBIDDEN",
            "Role {} is not permitted for this operation.".format(user_role),
        )
    return user_id, user_role
