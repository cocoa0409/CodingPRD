"""Auth header extraction and role checking (PRD section 2.1)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = (
    "ProgramCoordinator",
    "ReferringProvider",
    "Specialist",
    "QualityReviewer",
    "BillingClerk",
)

ANY_ROLE = ROLES


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return uid, role


def require_roles(*allowed):
    uid, role = auth_context()
    if role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Caller role %s is not authorized for this endpoint" % role,
        )
    return uid, role
