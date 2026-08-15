"""Auth middleware (PRD §2.1, validations priority 1-2).

Every request carries X-User-ID and X-User-Role. Seven recognized roles.
"""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = (
    "PlantAdmin",
    "StructuralDesigner",
    "PressOperator",
    "FinishingOperator",
    "KittingLead",
    "BrandQuality",
    "BillingClerk",
)
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    """Validate identity headers, then endpoint role permission.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and the role recognized",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            403,
            "Role %s is not permitted for this endpoint" % role,
        )
    return user_id, role
