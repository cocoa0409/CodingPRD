"""Authentication and RBAC middleware."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import g, request

from app.errors import make_error


VALID_ROLES = {
    "Trader",
    "RiskOfficer",
    "ComplianceOfficer",
    "SettlementOperator",
    "MarketDataSystem",
}


def extract_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        raise make_error("ERR_AUTH_REQUIRED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_auth(allowed_roles: Iterable[str]) -> Callable:
    allowed = tuple(allowed_roles)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            _, role = extract_auth()
            if role not in allowed:
                raise make_error("ERR_FORBIDDEN")
            return func(*args, **kwargs)

        return wrapper

    return decorator
