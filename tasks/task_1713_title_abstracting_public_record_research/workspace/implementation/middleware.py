"""Auth middleware: X-User-ID / X-User-Role headers and role authorization."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Client", "Abstracter", "Examiner", "OperationsManager"}
ALL_ROLES = ["Client", "Abstracter", "Examiner", "OperationsManager"]


def authenticate(allowed_roles):
    """Priority 1 (headers present + declared role -> 401) then
    priority 2 (role permitted on endpoint -> 403).
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-ID and X-User-Role headers must be present",
        )
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, f"undeclared role: {role}")
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role


def forbidden(message):
    return ApiError(ERR_FORBIDDEN, 403, message)
