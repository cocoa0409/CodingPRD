"""Bands 1 and 2: authentication and role authorisation (PRD 2.1, 2.10)."""
from flask import request

from errors import ApiError

ROLES = ("BondedCarrier", "CBPOfficer", "FPFOfficer", "SuretyAgent")
ALL_ROLES = ROLES


def actor():
    """Band 1. Returns (user_id, role) or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role == "":
        # SCAFFOLD spells the header X-Role; the PRD spells it X-User-Role.
        role = request.headers.get("X-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id.strip(), role


def require(*allowed):
    """Bands 1 then 2.  Returns (user_id, role)."""
    user_id, role = actor()
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role
