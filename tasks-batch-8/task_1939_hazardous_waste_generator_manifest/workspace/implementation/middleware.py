"""Auth middleware: validates X-User-ID / X-User-Role headers."""

from __future__ import annotations

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = {"EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent"}


def get_auth() -> tuple[str, str]:
    """Extract (user_id, role). Raises ApiError if headers invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing or role not declared",
        )
    return user_id, role


def require_roles(*allowed: str) -> tuple[str, str]:
    """Validate auth headers AND that the role is in the allowed list."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, f"Role {role} not permitted for this endpoint")
    return user_id, role
