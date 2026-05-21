"""Authentication / authorization middleware.

Reads X-User-ID + X-User-Role headers and enforces:
    1. ERR_MISSING_AUTH (401) — header presence
    2. ERR_FORBIDDEN   (403) — role allow-list per endpoint
"""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .errors import ApiError, ERR_FORBIDDEN, ERR_MISSING_AUTH


VALID_ROLES = {"Driver", "CarrierSafetyOfficer", "FMCSAAuditor", "PlatformAdmin"}


def _check_headers() -> None:
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role:
        raise ApiError(ERR_MISSING_AUTH, 401, "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError(ERR_MISSING_AUTH, 401, f"Unparsable X-User-Role: {role}")
    g.user_id = user_id
    g.user_role = role


def require_auth(allowed_roles: Iterable[str]):
    """Decorator factory — checks auth and authorisation."""
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
