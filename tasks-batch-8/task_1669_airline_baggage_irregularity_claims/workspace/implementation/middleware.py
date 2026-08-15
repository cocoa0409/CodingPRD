"""Auth header extraction and role checking per PRD §2.1 / validations priority 1-3."""

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

VALID_ROLES = {"SystemAdmin", "BaggageServiceAgent", "ClaimsAdjuster", "Passenger"}


def get_auth():
    """Return (user_id, role) or raise ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID header missing or malformed",
        )
    if not role or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header missing or malformed",
        )
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce header presence + role membership.

    Sets `request.auth_user_id` and `request.auth_role` for downstream use.
    """
    allowed = set(roles)

    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    403,
                    f"Role {role} is not permitted for this endpoint",
                )
            request.auth_user_id = user_id
            request.auth_role = role
            return fn(*args, **kwargs)

        return inner

    return wrapper
