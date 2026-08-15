"""Auth header extraction and role checking (PRD section 2.1)."""
import functools

from flask import g, request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

RECOGNIZED_ROLES = {
    "CathLabScheduler",
    "InterventionalCardiologist",
    "CathLabTechnologist",
    "RecoveryNurseManager",
    "RegistryCoordinator",
}

ALL_ROLES = tuple(sorted(RECOGNIZED_ROLES))


def require_roles(*allowed):
    """Validate X-User-ID / X-User-Role, then authorize the role.

    Priority 1: headers present and well-formed (role must be one of the five
    recognized values) -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
    Priority 2: role permitted for this endpoint -> ERR_INSUFFICIENT_PERMISSIONS (403).
    """
    allowed_set = set(allowed)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if (
                uid is None
                or not isinstance(uid, str)
                or not uid.strip()
                or role is None
                or role not in RECOGNIZED_ROLES
            ):
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must be present and well-formed",
                    400,
                )
            if role not in allowed_set:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    "Role %s is not permitted for this endpoint" % role,
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
