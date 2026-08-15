"""Auth header extraction and role checking (PRD §2.1; validations p1/p2)."""

from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = {
    "SystemAdmin",
    "RecoverySpecialist",
    "RecoverySupervisor",
    "RecoveryAccountant",
    "EstateRecoveryOfficer",
}

ALL_ROLES = (
    "SystemAdmin",
    "RecoverySpecialist",
    "RecoverySupervisor",
    "RecoveryAccountant",
    "EstateRecoveryOfficer",
)


def require_roles(*allowed):
    """Priority 1: headers present/well-formed. Priority 2: role authorized."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if (
                user_id is None
                or not user_id.strip()
                or role is None
                or role not in ROLES
            ):
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must be present and well-formed",
                    400,
                )
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    "Caller role is not authorized for this endpoint",
                    403,
                )
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
