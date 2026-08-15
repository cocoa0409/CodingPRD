"""Auth header extraction and role checking (per PRD §2.1)."""
from flask import request

import errors

ROLES = {
    "StationAdmin",
    "AirlineRep",
    "PadOperator",
    "Inspector",
    "EnvironmentalOfficer",
    "BillingClerk",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Authenticate and require role membership; returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.forbidden()
    return user_id, role


def require_own_airline(user_id, airline_id):
    if airline_id != user_id:
        raise errors.forbidden(
            "AirlineRep touching another airline's resource"
        )
