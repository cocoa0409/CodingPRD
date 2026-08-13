"""Authentication / authorization (PRD 2.1)."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = [
    "FleetManager",
    "SalesRep",
    "RentalCoordinator",
    "ServiceDispatcher",
    "Technician",
    "TrainingRegistrar",
    "LeaseManager",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED, "Role %s is not authorized for this endpoint" % role)
