"""Auth extraction (PRD §2.1 / SCAFFOLD validations priority 1-2)."""
from flask import request
from errors import err

ROLES = {
    "Anonymous",
    "Landlord",
    "Renter",
    "UnderwritingAgent",
    "ClaimsAdjuster",
    "ComplianceOfficer",
    "PlatformAdmin",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Priority 1: X-User-ID and X-User-Role headers must be present and declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID/X-User-Role headers.")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """Priority 2: caller's role must be permitted to perform this operation."""
    if caller.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", f"Role {caller.role} is not permitted to perform this operation.")


def require_ownership(caller, expected_owner_id, role_that_owns):
    """Ownership check for entity-backed roles (Landlord/Renter); no-op for opaque roles."""
    if caller.role == role_that_owns and caller.user_id != expected_owner_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this resource.")
