"""Authentication middleware — header parsing and role check.

Per PRD §2.1, every request (except POST /_clock/advance and POST /_sweep/run
which are also restricted to PlatformAdmin and therefore still need headers)
must carry X-User-ID and X-User-Role with X-User-Role in
{Veteran, VAClerk, Rater, Counselor, PlatformAdmin}.
"""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, request

from .errors import ApiError

VALID_ROLES = {"Veteran", "VAClerk", "Rater", "Counselor", "PlatformAdmin"}


def _extract_headers() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", f"unknown role: {role}")
    return user_id, role


def require_auth(roles: list[str] | None = None) -> Callable:
    """Decorator factory: validate headers, then check role membership.

    Role-membership failures raise ERR_FORBIDDEN. Auth-header failures raise
    ERR_UNAUTHENTICATED. Ownership (e.g., Veteran X-User-ID must equal the
    target's veteran_id) is enforced inside the route, not here.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_headers()
            if roles is not None and role not in roles:
                raise ApiError("ERR_FORBIDDEN", f"role {role} not permitted")
            g.user_id = user_id
            g.user_role = role
            return func(*args, **kwargs)

        return wrapper

    return decorator
