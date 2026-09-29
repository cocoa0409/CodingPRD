"""Authentication, endpoint authorisation and StationOperator ownership binding."""
from flask import request

from constants import HDR_USER_ID, HDR_USER_ROLE, ROLES
from errors import raise_error


def actor(*allowed_roles):
    """Validation priorities 10 and 20: authenticate then authorise.

    Returns (user_id, role).
    """
    user_id = request.headers.get(HDR_USER_ID)
    role = request.headers.get(HDR_USER_ROLE)
    if not user_id or not str(user_id).strip() or not role or role not in ROLES:
        raise_error("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise_error("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def require_station_owner(role, user_id, station_id):
    """Validation priority 30 — only meaningful for StationOperator."""
    if role != "StationOperator":
        return
    if station_id is None:
        return
    if user_id != station_id:
        raise_error("ERR_STATION_OWNERSHIP_MISMATCH")
