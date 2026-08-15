"""Auth header extraction and role checking (PRD §2.1, validations priority 1-2)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ALL_ROLES = (
    "CenterAdmin",
    "ProgramManager",
    "DesignLead",
    "ShopTechnician",
    "QualityInspector",
    "FinanceClerk",
    "CustomerRep",
)


def auth(*allowed_roles):
    """Validate X-User-ID / X-User-Role headers and the endpoint role list.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) then
    ERR_FORBIDDEN_ROLE (403), in validation-priority order.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE, 403,
            f"Role {role} is not permitted for this endpoint",
        )
    return user_id, role
