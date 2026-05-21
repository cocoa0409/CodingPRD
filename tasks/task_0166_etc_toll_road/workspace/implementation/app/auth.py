"""Auth middleware: extract caller identity & enforce role allowlists."""
from functools import wraps
from typing import Iterable

from flask import request

from .errors import ApiError

VALID_ROLES = {"AccountHolder", "AgencyAdmin", "GantryOperator"}


def get_caller():
    """Return (user_id, role) after validating both headers exist."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH", 401, "X-User-ID and X-User-Role headers are required.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_INVALID_ROLE", 401, f"Unknown role: {role}")
    return user_id, role


def require_roles(*allowed: str):
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_caller()
            if role not in allowed_set:
                raise ApiError("ERR_FORBIDDEN", 403, "Role is not permitted for this endpoint.")
            request.caller_id = user_id  # type: ignore[attr-defined]
            request.caller_role = role  # type: ignore[attr-defined]
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def check_account_holder_owns(account_id: str) -> None:
    """If the caller is an AccountHolder, enforce that X-User-ID == account_id."""
    role = getattr(request, "caller_role", None)
    caller_id = getattr(request, "caller_id", None)
    if role == "AccountHolder" and caller_id != account_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Account holders may only access their own account.")
