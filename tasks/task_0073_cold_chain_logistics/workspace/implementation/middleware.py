"""Auth and RBAC middleware for the cold-chain-logistics API."""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import err


RECOGNIZED_ROLES = {
    "SHIPPER",
    "CARRIER",
    "DRIVER",
    "CONSIGNEE",
    "DISPATCHER",
    "COMPLIANCE_OFFICER",
    "INSURANCE_ADJUSTER",
    "SYSTEM",
}


def auth_context() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        err("ERR_AUTH_MISSING")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator to enforce role-based access on an endpoint."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = auth_context()
            if role not in RECOGNIZED_ROLES:
                err("ERR_FORBIDDEN")
            if role not in allowed:
                err("ERR_FORBIDDEN")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
