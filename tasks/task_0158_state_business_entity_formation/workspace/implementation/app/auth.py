"""Auth middleware: validates X-User-ID + X-User-Role headers."""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Callable, Iterable

from flask import g, request

from .errors import APIError, err_forbidden, err_invalid_role, err_missing_auth


VALID_ROLES = {"Filer", "StateRegistrar", "TaxOfficer", "ComplianceOfficer", "RegisteredAgentService", "TestHarness"}


@dataclass
class Caller:
    user_id: str
    role: str


def _read_caller() -> Caller:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise err_missing_auth()
    if role not in VALID_ROLES:
        raise err_invalid_role(f"Unknown role: {role!r}")
    return Caller(user_id=user_id.strip(), role=role.strip())


def require_auth(allowed_roles: Iterable[str]) -> Callable:
    """Decorator: parse auth, verify role, attach a `Caller` to `g.caller`."""
    allowed = set(allowed_roles)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller = _read_caller()
            if caller.role not in allowed:
                raise err_forbidden(f"Role {caller.role!r} not authorized for this endpoint")
            g.caller = caller
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_caller() -> Caller:
    caller = getattr(g, "caller", None)
    if caller is None:
        # Should never happen if @require_auth was applied. Fail loud.
        raise APIError("ERR_INTERNAL", "auth middleware missing", 500)
    return caller
