"""Auth + RBAC middleware. Reads X-User-Role and X-User-ID headers per PRD §2.1."""

from flask import request, g

from errors import AppError, ERR_AUTH_MISSING, ERR_FORBIDDEN, ERROR_STATUS

VALID_ROLES = {
    "PlatformAdmin",
    "HotlineOperator",
    "Dispatcher",
    "DepartmentHandler",
    "Supervisor",
    "SurveyAgent",
}


def require_auth():
    """Validate that both headers are present and X-User-Role is recognised. Store in flask.g."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # Priority 1: role header present and recognised.
    if not role or role not in VALID_ROLES:
        raise AppError(
            ERR_AUTH_MISSING,
            "X-User-Role header is missing or invalid.",
            ERROR_STATUS[ERR_AUTH_MISSING],
        )
    # Priority 2: id header present.
    if not user_id:
        raise AppError(
            ERR_AUTH_MISSING,
            "X-User-ID header is missing.",
            ERROR_STATUS[ERR_AUTH_MISSING],
        )
    g.role = role
    g.user_id = user_id


def require_role(*allowed_roles):
    """Priority 3: check the caller's role is in the allowed set."""
    if g.role not in allowed_roles:
        raise AppError(
            ERR_FORBIDDEN,
            f"Role {g.role} is not authorized for this endpoint.",
            ERROR_STATUS[ERR_FORBIDDEN],
        )
