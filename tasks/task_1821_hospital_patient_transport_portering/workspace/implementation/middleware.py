"""Authentication and role-checking helpers (PRD section 2.1).

Every request carries X-User-ID and X-User-Role. The five declared roles are
RequestingClinician, TransportDispatcher, Transporter, HousekeepingStaff, and
TransportSupervisor.
"""

from flask import request

from errors import ApiError

ROLES = {
    "RequestingClinician",
    "TransportDispatcher",
    "Transporter",
    "HousekeepingStaff",
    "TransportSupervisor",
}


def auth():
    """Tier 1: headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*roles):
    """Tier 1 + endpoint-level tier 2 role gate."""
    uid, role = auth()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "role {} is not permitted on this endpoint".format(role))
    return uid, role


def forbidden(message="forbidden"):
    raise ApiError("ERR_FORBIDDEN_ROLE", 403, message)
