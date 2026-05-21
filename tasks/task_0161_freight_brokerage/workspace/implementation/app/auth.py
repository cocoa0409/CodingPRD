"""Authentication / authorisation middleware.

PRD §2.1 fixes the headers:

* ``X-User-ID``  — opaque or entity id depending on role
* ``X-User-Role`` — one of PlatformAdmin | BrokerOps | CarrierOps | ShipperUser | CarrierUser

Missing/invalid headers yield ``ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER``
(HTTP 400).  Well-formed but non-allowed roles yield
``ERR_INSUFFICIENT_PERMISSIONS`` (HTTP 403).
"""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)


VALID_ROLES = {
    "PlatformAdmin",
    "BrokerOps",
    "CarrierOps",
    "ShipperUser",
    "CarrierUser",
}


def _check_headers() -> None:
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Missing X-User-ID or X-User-Role header.",
        )
    if role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            f"Unrecognised X-User-Role: {role}",
        )
    g.user_id = user_id
    g.user_role = role


def require_auth(allowed_roles: Iterable[str]):
    """Decorator factory: check headers, then RBAC against ``allowed_roles``."""
    allowed_set = set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _check_headers()
            if g.user_role not in allowed_set:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    "Role not permitted on this endpoint.",
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator
