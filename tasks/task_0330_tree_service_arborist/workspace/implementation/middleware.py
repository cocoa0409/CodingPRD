"""Auth header extraction and role authorization (PRD section 2.1).

Headers:
  X-User-ID   — acting user identifier (opaque)
  X-User-Role — one of: Dispatcher, Arborist, FinanceClerk, Client

Missing header or unknown role -> ERR_MISSING_OR_INVALID_AUTH (401).
Valid headers but role not permitted for the operation -> ERR_FORBIDDEN_ROLE (403).
"""
from functools import wraps

from flask import g, request

import errors
from errors import ApiError

VALID_ROLES = {"Dispatcher", "Arborist", "FinanceClerk", "Client"}


def authenticate():
    """Validate auth headers; populate g.user_id and g.role. Raise on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(errors.ERR_MISSING_OR_INVALID_AUTH, 401,
                       "Missing or invalid authentication headers.")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that g.role is in allowed set."""
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed_set:
                raise ApiError(errors.ERR_FORBIDDEN_ROLE, 403,
                               "Role not permitted for this operation.")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# All four roles may call GET endpoints.
ALL_ROLES = ("Dispatcher", "Arborist", "FinanceClerk", "Client")
