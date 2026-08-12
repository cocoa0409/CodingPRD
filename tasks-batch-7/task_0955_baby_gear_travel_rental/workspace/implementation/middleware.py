"""Auth: X-User-ID + X-User-Role headers; role must be one of the five declared
roles, else ERR_UNAUTHENTICATED (401). Role not permitted for the endpoint ->
ERR_FORBIDDEN (403)."""
from flask import request

from errors import ApiError

ROLES = {"Anonymous", "Customer", "HotelPartner", "Inspector", "OperationsAdmin"}


def authenticate():
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*roles):
    uid, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data
