"""Authentication / authorization per PRD §2.1 and validation pipeline §2.6."""

from flask import request

from errors import (ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT,
                    ERR_FORBIDDEN_ROLE)

ROLES = {
    "HRAdmin",
    "HiringManager",
    "Buddy",
    "NewHire",
    "ITProvisioner",
    "BackgroundAdjudicator",
    "PayrollOps",
}

ALL_ROLES = [
    "HRAdmin", "HiringManager", "Buddy", "NewHire", "ITProvisioner",
    "BackgroundAdjudicator", "PayrollOps",
]


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present; role is declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT, 400,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*roles):
    """Priority 1 + 2: authentication, then role permitted for the endpoint."""
    uid, role = authenticate()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       f"Role {role} is not permitted on this endpoint")
    return uid, role
