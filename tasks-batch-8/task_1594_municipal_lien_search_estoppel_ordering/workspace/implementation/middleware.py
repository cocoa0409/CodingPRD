"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ROLES = ("TitleAgent", "ResearchAnalyst", "QAReviewer", "ProviderAdmin")


def auth_context():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID header is missing or malformed",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header is missing or malformed",
        )
    return uid, role


def require_roles(*allowed):
    """Validate headers, then enforce that the caller's role is authorized."""
    uid, role = auth_context()
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            403,
            f"Role {role} is not authorized for this endpoint",
        )
    return uid


def require_any_role():
    """Read endpoints: any of the four authenticated roles."""
    uid, _role = auth_context()
    return uid
