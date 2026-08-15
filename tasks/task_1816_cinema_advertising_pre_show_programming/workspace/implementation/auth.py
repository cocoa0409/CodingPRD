"""Auth middleware (SCAFFOLD 1.4 priorities 1-3 / PRD 2.1)."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_THEATER_SCOPE_MISMATCH,
)

ROLES = {"NetworkOps", "SalesManager", "TheaterOps", "Auditor"}
ALL_ROLES = ROLES


def require(allowed_roles):
    """Validate context headers (priority 1) and endpoint role (priority 2).
    Returns the caller's X-User-ID."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required and the role must be "
            "one of NetworkOps, SalesManager, TheaterOps, Auditor",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"role {role} is not permitted on this endpoint",
        )
    return user_id


def check_theater_scope(user_id, theater_id):
    """Priority 3: TheaterOps X-User-ID must equal the owning Theater.id."""
    if user_id != theater_id:
        raise ApiError(
            ERR_THEATER_SCOPE_MISMATCH,
            403,
            "TheaterOps identity does not match the theater owning the target "
            "showtime's screen",
        )
