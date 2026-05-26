"""Auth & RBAC middleware. Reads X-User-ID and X-User-Role per PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
)


# Five recognized roles per PRD §2.1 and SCAFFOLD §1.7.
KNOWN_ROLES = {
    "Anonymous",
    "Owner",
    "Sitter",
    "PlatformAdmin",
    "ClaimsAdjuster",
}


def _extract_auth(allow_anonymous: bool = False):
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        if allow_anonymous:
            # Registration endpoints accept missing headers — treat as Anonymous.
            g.user_id = None
            g.user_role = "Anonymous"
            return None, "Anonymous"
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or empty X-User-ID / X-User-Role header.")
    if user_role not in KNOWN_ROLES:
        raise ApiError(ERR_FORBIDDEN, f"Unknown role: {user_role}.")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_auth(roles: Iterable[str] | None = None):
    """Decorator: enforce auth + (optional) role allow-list for an endpoint.

    `roles=None` means "any authenticated, known role".
    """
    allowed = set(roles) if roles is not None else None

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            allow_anon = allowed is not None and "Anonymous" in allowed
            user_id, user_role = _extract_auth(allow_anonymous=allow_anon)
            if allowed is not None and user_role not in allowed:
                raise ApiError(ERR_FORBIDDEN, f"Role {user_role} not permitted for this endpoint.")
            return fn(*args, **kwargs)

        return wrapper

    return deco
