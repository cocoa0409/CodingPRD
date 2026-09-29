"""Header extraction, role checking and GroundTenant ownership (PRD 2.1)."""

from flask import request

from errors import ApiError

ROLES = (
    "LessorAdmin",
    "AssetManager",
    "LeaseAccountant",
    "GroundTenant",
    "MortgageeAgent",
    "Arbitrator",
)

ALL_ROLES = set(ROLES)


def identity():
    """Return (user_id, role) after validating both headers.

    A missing, empty or unknown role -- and a missing or empty user id --
    is ERR_UNAUTHORIZED at HTTP 403.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHORIZED", "The X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHORIZED", "The X-User-Role header is required.")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
    return str(user_id).strip(), role


def require(allowed):
    """Validate the headers and confirm the role is authorised here."""
    user_id, role = identity()
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role '%s' is not authorised for this operation." % role,
        )
    return user_id, role


def owns_lease(user_id, role, lease):
    """Ownership check for a GroundTenant acting on a lease-scoped resource."""
    if role != "GroundTenant":
        return
    if lease is None or lease.get("lessee_id") != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "The acting ground tenant is not the lessee of that lease.",
        )
