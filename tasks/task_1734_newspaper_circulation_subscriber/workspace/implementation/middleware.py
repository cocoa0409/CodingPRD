"""Auth: X-User-ID + X-User-Role headers (PRD 2.1). Missing either header or an
unrecognized role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). Role
recognized but not permitted for the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
Subscriber-role callers are scoped to their own account chain; violations ->
ERR_NOT_OWN_RESOURCE (403)."""
from flask import request

from errors import ApiError

ROLES = ("Subscriber", "ServiceRep", "DistrictManager", "CirculationDirector")

STAFF = ("ServiceRep", "DistrictManager", "CirculationDirector")
ALL = ROLES


def authenticate():
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return uid, role


def require_roles(*roles):
    uid, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       "Role not permitted for this endpoint")
    return uid, role


def own_check(uid, role, subscriber_id):
    """Subscriber-role ownership: the target's subscriber chain must equal
    X-User-ID."""
    if role == "Subscriber" and subscriber_id != uid:
        raise ApiError("ERR_NOT_OWN_RESOURCE", 403,
                       "Resource is outside the caller's own account chain")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data
