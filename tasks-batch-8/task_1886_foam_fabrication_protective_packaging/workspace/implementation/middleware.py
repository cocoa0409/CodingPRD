"""Auth header extraction and role checking, per PRD §2.1 and scaffold validations 1-3."""
from flask import request

import errors
from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "SalesEngineer",
    "DesignEngineer",
    "QualityEngineer",
    "PlantManager",
    "Customer",
)

# Every role except PlatformAdmin — the five business roles (PRD §2.1).
BUSINESS_ROLES = (
    "SalesEngineer",
    "DesignEngineer",
    "QualityEngineer",
    "PlantManager",
    "Customer",
)


def get_auth_context():
    """Validate X-User-ID and X-User-Role headers. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            errors.ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and role must be one of the six recognized roles",
            401,
        )
    return user_id, role


def require_role(role, allowed_roles):
    """Check the caller's role is permitted on this endpoint (ERR_UNAUTHORIZED)."""
    if role not in allowed_roles:
        raise ApiError(
            errors.ERR_UNAUTHORIZED,
            f"Role {role} is not authorized for this endpoint",
            403,
        )


def require_business_role(role):
    require_role(role, BUSINESS_ROLES)


def forbid_unless_owner(role, user_id, owner_customer_id):
    """Customer-role ownership gate (ERR_FORBIDDEN_OWNERSHIP).

    Resources with no owning customer (owner_customer_id None) are readable by
    any business role.
    """
    if role == "Customer" and owner_customer_id is not None and owner_customer_id != user_id:
        raise ApiError(
            errors.ERR_FORBIDDEN_OWNERSHIP,
            "Customer role may act only on its own resources",
            403,
        )
