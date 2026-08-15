"""Auth middleware (PRD §2.1): identity headers, role authorization, ownership."""

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
)

DECLARED_ROLES = {
    "PlantManager",
    "ProductionPlanner",
    "LineOperator",
    "QAManager",
    "WarehouseLead",
    "CustomerRep",
    "ClaimsAdjuster",
}

ALL_ROLES = DECLARED_ROLES


def authenticate(allowed_roles):
    """Priority 1 (headers present, role declared) then priority 2 (role allowed).

    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not str(user_id).strip()
        or role is None
        or not str(role).strip()
        or role not in DECLARED_ROLES
    ):
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-ID and X-User-Role headers must be present and X-User-Role "
            "must be a declared role",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role


def check_ownership(user_id, owner_id, what="resource"):
    """Priority 7: entity-backed CustomerRep ownership checks."""
    if owner_id != user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            f"caller does not own this {what}",
        )
