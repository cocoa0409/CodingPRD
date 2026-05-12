"""Auth header extraction and RBAC checking (PRD §2.1).

Validation priorities (PRD §2.10):
1. Headers present and non-empty -> ERR_AUTH_REQUIRED (401)
2. Role recognized              -> ERR_UNKNOWN_ROLE (401)
3. Role permitted for endpoint  -> ERR_FORBIDDEN (403)
"""

from __future__ import annotations

from functools import wraps

from flask import g, request

from errors import (
    ERR_AUTH_REQUIRED,
    ERR_FORBIDDEN,
    ERR_UNKNOWN_ROLE,
    raise_api_error,
)


VALID_ROLES = {"SystemOperator", "CommunityAdmin", "AppealReviewer", "Resident"}


def extract_user_context():
    """Read X-User-ID and X-User-Role; reject when missing/empty/unknown."""
    user_id = request.headers.get("X-User-ID", "")
    user_role = request.headers.get("X-User-Role", "")
    if not user_id or not user_role:
        raise_api_error(
            ERR_AUTH_REQUIRED,
            "X-User-ID and X-User-Role headers are required.",
        )
    if user_role not in VALID_ROLES:
        raise_api_error(
            ERR_UNKNOWN_ROLE,
            f"Unknown role: {user_role}",
        )
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles: str):
    """Enforces auth + RBAC. Use as @require_roles('CommunityAdmin', 'Resident')."""
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            extract_user_context()
            if g.user_role not in allowed_set:
                raise_api_error(
                    ERR_FORBIDDEN,
                    f"Role {g.user_role} is not permitted to invoke this endpoint.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
