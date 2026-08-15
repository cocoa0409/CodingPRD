"""Auth: X-User-ID + X-User-Role headers; role membership per endpoint."""
from flask import request
from errors import err

ROLES = [
    "PlantManager", "MillerOperator", "QualityInspector", "LineScheduler",
    "SanitationTech", "PackagingLead", "RouteDispatcher",
]
_ROLE_SET = set(ROLES)


def authorize(allowed_roles):
    """Returns (user_id, role). Raises 401 / 403 per priority 1-2."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in _ROLE_SET:
        err("ERR_UNAUTHENTICATED", 401,
            "X-User-ID and X-User-Role headers are required and role must be recognized")
    if role not in allowed_roles:
        err("ERR_FORBIDDEN", 403, "Role is not permitted for this endpoint")
    return uid, role
