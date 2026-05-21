"""Authentication / authorization middleware.

Reads X-User-ID + X-User-Role headers and enforces the priority-ordered
validation chain from SCAFFOLD §1.4 (auth → role → forbidden).
"""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_ROLE,
    ERR_MISSING_AUTH,
)


VALID_ROLES = {"Requester", "Officer", "AppealAuthority", "ThirdParty", "ClockOperator"}


def _check_headers() -> None:
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise ApiError(ERR_MISSING_AUTH, 401, "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError(ERR_INVALID_ROLE, 401, f"Unknown role: {role}")
    g.user_id = user_id
    g.user_role = role


def require_auth(allowed_roles: Iterable[str]):
    """Decorator factory: ensures auth headers are valid and role is permitted."""

    allowed_set = set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _check_headers()
            if g.user_role not in allowed_set:
                raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted on this endpoint.")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_role_any():
    """Decorator: any of the five recognised roles is acceptable."""

    return require_auth(VALID_ROLES)
