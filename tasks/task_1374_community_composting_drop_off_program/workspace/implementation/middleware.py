"""Auth header extraction and role checking (SCAFFOLD §1.4 / PRD §2.1)."""

from flask import request

import errors

ROLES = {
    "Anonymous",
    "ProgramAdmin",
    "SiteHost",
    "Participant",
    "RouteOperator",
    "ProcessingPartner",
    "MunicipalAuditor",
}

ALL_ROLES = list(ROLES)


def get_context():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.raise_err(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing or role unrecognized",
        )
    return user_id, role


def require_roles(*roles):
    """Validate auth headers and enforce role membership."""
    user_id, role = get_context()
    if role not in roles:
        errors.raise_err(
            errors.ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this endpoint",
        )
    return user_id, role
