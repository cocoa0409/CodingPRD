"""Auth header extraction and RBAC checking (PRD §2.1)."""

from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from errors import (
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_api_error,
)


VALID_ROLES = {
    "ClaimsAdmin",
    "PolicyAdmin",
    "ClaimsReviewer",
    "ClaimsApprover",
    "BatchApprover",
    "BatchExecutor",
    "PayoutOperator",
    "Auditor",
    "system",
    "Any",
}


def _extract_user_context():
    """Read X-User-ID and X-User-Role; reject if missing/empty."""
    user_id = request.headers.get("X-User-ID", "")
    user_role = request.headers.get("X-User-Role", "")
    if not user_id or not user_role:
        raise_api_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required.",
        )
    if user_role not in VALID_ROLES:
        raise_api_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            f"X-User-Role '{user_role}' is not recognised.",
        )
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles: str):
    """Decorator that enforces auth + RBAC.

    `Any` in allowed_roles means any authenticated role passes the role check.
    """
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_user_context()
            role = g.user_role
            if "Any" in allowed_set:
                # Any authenticated role permitted.
                return fn(*args, **kwargs)
            if role not in allowed_set:
                raise_api_error(
                    ERR_FORBIDDEN_FOR_ROLE,
                    f"Role {role} is not permitted to access this endpoint.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
