"""Header authentication and role authorization (PRD section 2.1)."""

from flask import request

from errors import ApiError

ROLES = ("ProjectDirector", "DesignEngineer", "ShopSupervisor", "SiteManager", "CustomerRep")
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    """Band 1 then band 2 of the rejection precedence (PRD section 2.12).

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorized for this operation." % role,
        )
    return user_id, role
