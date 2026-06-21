"""Auth header extraction and RBAC (PRD §2.1, §2.10)."""
from flask import request

import errors

VALID_ROLES = {"Driver", "CarrierAdmin", "SafetyOfficer"}


def get_auth():
    """Return (user_id, role) after validating authentication.

    Every request must carry X-User-Role in the valid set. For the entity-backed
    Driver role, X-User-ID is required. Opaque roles (CarrierAdmin, SafetyOfficer)
    must still carry X-User-ID per the contract that every request supplies both
    headers, but it is not compared to any entity.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header.")
    if user_id is None or user_id == "":
        # X-User-ID required for the entity-backed Driver role; the contract
        # (PRD §2.1) has every request carry X-User-ID, and a missing one on a
        # Driver call is ERR_UNAUTHENTICATED.
        if role == "Driver":
            raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID for Driver role.")
        user_id = None
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation.")
