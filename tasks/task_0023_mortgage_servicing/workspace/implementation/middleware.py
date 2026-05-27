"""Auth & RBAC middleware. Reads X-User-ID and X-User-Role per PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)


KNOWN_ROLES = {"LoanServicer", "ComplianceOfficer", "Borrower"}


def _extract_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header.")
    if user_role not in KNOWN_ROLES:
        raise ApiError(ERR_UNAUTHORIZED, f"Unknown role: {user_role}.")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_auth(roles: Iterable[str] | None = None):
    """Decorator: enforce auth + (optional) role allow-list."""
    allowed = set(roles) if roles is not None else None

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = _extract_auth()
            if allowed is not None and user_role not in allowed:
                raise ApiError(ERR_UNAUTHORIZED, f"Role {user_role} not permitted for this endpoint.")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def no_auth():
    """Decorator: explicitly no auth (only for /_clock/set_current_utc per PRD §2.4)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    return deco
