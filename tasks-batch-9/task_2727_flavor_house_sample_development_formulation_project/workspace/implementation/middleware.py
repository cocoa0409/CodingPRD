"""Auth header extraction and RBAC (PRD §2.1, scaffold §1.7)."""

from flask import request

from errors import ApiError

ROLES = (
    "AccountManager",
    "TechnicalDirector",
    "Flavorist",
    "RegulatoryAffairs",
    "LabTech",
    "PurchasingManager",
)

ALL_ROLES = ROLES


def auth(allowed_roles):
    """Validation priority 10 then 20.

    Returns (user_id, role).  `allowed_roles` of ALL_ROLES means every
    authenticated role may call the endpoint.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "role %s may not call this endpoint" % role)
    return user_id, role
