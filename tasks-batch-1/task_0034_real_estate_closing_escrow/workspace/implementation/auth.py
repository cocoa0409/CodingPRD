"""Auth + RBAC middleware (PRD §2.1, §2.10).

Every request must carry X-User-ID and X-User-Role headers. Role must be one
of EscrowOfficer / TitleAgent / ComplianceOfficer (priority 1 in §1.4).
Endpoint-level role authorisation is priority 2.
"""
from __future__ import annotations

from functools import wraps

from flask import g, request

from errors import (
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    err,
)

VALID_ROLES = {"EscrowOfficer", "TitleAgent", "ComplianceOfficer"}


def authenticate() -> tuple[str, str]:
    """Return (user_id, role) or raise APIError(ERR_UNAUTHENTICATED).

    Per PRD §2.1: X-User-Role must be one of three exact strings. X-User-ID
    carries the caller's identifier. A missing or unrecognised role -> 401.
    """
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED)
    # Per the PRD, X-User-ID is required as the caller's identifier; treat empty as unauthenticated.
    if not user_id:
        raise err(ERR_UNAUTHENTICATED)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed_roles: str):
    """Decorator: enforce auth (priority 1) then role authorisation (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed_roles:
                raise err(ERR_FORBIDDEN)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
