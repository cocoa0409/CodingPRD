from flask import request

from errors import ApiError

ROLES = {
    "ShopManager",
    "ToolingEngineer",
    "Laminator",
    "CureTechnician",
    "QualityInspector",
    "EHSOfficer",
}

ALL_ROLES = sorted(ROLES)


def authenticate(allowed_roles):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_FORBIDDEN)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role %s is not permitted for this endpoint" % role)
    return uid, role
