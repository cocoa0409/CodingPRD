"""Auth middleware: X-User-ID / X-User-Role extraction and role gating."""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ALL_ROLES = (
    "SponsorSignatory",
    "BadgingOfficer",
    "SecurityManager",
    "Auditor",
    "AccessControlSystem",
)


def require_roles(*roles):
    """Validate auth headers (priority 1) and role authorization (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if (
                user_id is None
                or role is None
                or not str(user_id).strip()
                or not str(role).strip()
            ):
                raise_err(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must be present and non-empty",
                )
            if role not in roles:
                raise_err(
                    ERR_FORBIDDEN_ROLE,
                    "Role '{}' is not authorized for this endpoint".format(role),
                )
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator
