"""Auth/RBAC middleware. Reads X-User-ID and X-User-Role from every request,
enforces role validity, and exposes the caller's identity to handlers.

Role names are spelled exactly as in PRD §2.1: PropertyManager, Owner,
MaintenanceStaff, CommitteeChair.
"""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from errors import (
    APIError,
    ERR_AUTH_INVALID_ROLE,
    ERR_AUTH_MISSING,
    ERR_FORBIDDEN,
)

VALID_ROLES = {"PropertyManager", "Owner", "MaintenanceStaff", "CommitteeChair"}


def extract_auth():
    """Pull X-User-ID / X-User-Role off the request and store on flask.g.
    Raises APIError(ERR_AUTH_MISSING / ERR_AUTH_INVALID_ROLE) on bad headers."""
    user_id = request.headers.get("X-User-ID", "").strip()
    user_role = request.headers.get("X-User-Role", "").strip()

    if not user_id or not user_role:
        raise APIError(ERR_AUTH_MISSING, "X-User-ID and X-User-Role are required.", 401)
    if user_role not in VALID_ROLES:
        raise APIError(ERR_AUTH_INVALID_ROLE, f"Unknown role '{user_role}'.", 401)

    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles: str):
    """Decorator: extract auth, then enforce that the caller's role is in `roles`."""
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            extract_auth()
            if g.user_role not in allowed:
                raise APIError(ERR_FORBIDDEN, "Role not authorized for this endpoint.", 403)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_any_authenticated(fn):
    """Decorator: just extract auth; no role gating beyond the four-role check."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        extract_auth()
        return fn(*args, **kwargs)
    return wrapper


def caller_is(role: str) -> bool:
    return getattr(g, "user_role", None) == role


def assert_role_in(roles: Iterable[str]) -> None:
    if g.user_role not in set(roles):
        raise APIError(ERR_FORBIDDEN, "Role not authorized for this endpoint.", 403)
