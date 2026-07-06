"""Auth middleware and RBAC helpers.

Auth priorities from PRD §2.6:
  10 — X-User-ID and X-User-Role are present and non-empty
  20 — X-User-Role is one of the six declared roles
  30 — For entity_backed roles (Resident, Moderator, BusinessOwner), X-User-ID
       matches a live entity of the corresponding type
  40 — Role is permitted for this endpoint

`Moderator` requires the referenced Resident.is_moderator == true.
`AgencyOfficer` and `PlatformAdmin` are opaque — no entity check.
`Anonymous` is a valid role name but is not accepted on any endpoint.
"""
from __future__ import annotations

from functools import wraps
from flask import g, request

from db import DB
from errors import Unauthenticated, Forbidden


VALID_ROLES = {"Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin", "Anonymous"}


def _resolve_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID", "")
    user_role = request.headers.get("X-User-Role", "")
    if not user_id or not user_role:
        raise Unauthenticated("Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise Unauthenticated(f"Unknown role: {user_role}")
    # entity-backed identity checks
    if user_role == "Resident":
        resident = DB.residents.get(user_id)
        if resident is None:
            raise Unauthenticated("X-User-ID does not match a live Resident")
    elif user_role == "Moderator":
        resident = DB.residents.get(user_id)
        if resident is None or not resident.get("is_moderator", False):
            raise Unauthenticated("X-User-ID does not match a live Moderator")
    elif user_role == "BusinessOwner":
        business = DB.businesses.get(user_id)
        if business is None:
            raise Unauthenticated("X-User-ID does not match a live Business")
    # Anonymous is never accepted on documented endpoints — leave to per-endpoint role check
    return user_id, user_role


def require_roles(*allowed_roles: str):
    """Decorator: enforce auth (priorities 10/20/30), then endpoint RBAC (priority 40)."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = _resolve_auth()
            g.user_id = user_id
            g.user_role = user_role
            if user_role not in allowed:
                raise Forbidden(f"Role {user_role} not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
