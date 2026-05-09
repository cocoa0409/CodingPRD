"""Authentication and role check middleware."""

from flask import g, request

import db
from errors import ApiError

ALL_ROLES = {"PlatformAdmin", "HRBP", "Manager", "Employee"}


def authenticate():
    """Resolve X-User-ID/X-User-Role headers; mutates flask.g.

    Priority:
      1. presence -> ERR_MISSING_AUTH (401)
      2. role valid -> ERR_INVALID_AUTH (401)
      3. for Manager/Employee: X-User-ID must resolve to an ACTIVE User -> ERR_USER_NOT_FOUND (404)
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH", 401, "X-User-ID and X-User-Role required")
    if role not in ALL_ROLES:
        raise ApiError("ERR_INVALID_AUTH", 401, f"X-User-Role '{role}' not recognized")
    if role in ("Manager", "Employee"):
        u = db.users.get(user_id)
        if not u or u.get("status") != "ACTIVE":
            raise ApiError("ERR_USER_NOT_FOUND", 404, "Acting user not found or not active")
    g.actor_user_id = user_id
    g.actor_role = role


def require_role(*allowed):
    """Raise ERR_FORBIDDEN if g.actor_role is not in allowed roles.

    'allowed' is the set of roles permitted to call the endpoint per the RBAC matrix.
    PlatformAdmin override (when applicable) should be passed in explicitly.
    """
    if g.actor_role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, f"Role '{g.actor_role}' not permitted")


def is_owner_or_co_owner(objective: dict, user_id: str) -> bool:
    if objective.get("owner_user_id") == user_id:
        return True
    for co in db.co_ownerships.values():
        if (co.get("objective_id") == objective["id"]
                and co.get("co_owner_user_id") == user_id
                and co.get("status") == "ACTIVE"):
            return True
    return False
