"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

# The system recognizes exactly four roles, spelled precisely (PRD §2.1).
ROLES = {"IntakeCoordinator", "Physician", "ClinicalManager", "BillingAdmin"}


def get_identity():
    """Return (user_id, role) from headers, raising ERR_UNAUTHENTICATED if either
    header is missing or malformed (priority 1, PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID / X-User-Role header")
    if role not in ROLES:
        # A malformed (unrecognized) role value is an authentication failure.
        raise err(ERR_UNAUTHENTICATED, "Malformed X-User-Role header")
    return user_id, role


def require_role(allowed_roles):
    """Validate presence (priority 1) then role membership (priority 2).

    Returns (user_id, role). Raises ERR_FORBIDDEN_ROLE if role not in allowed set.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role '%s' is not permitted for this operation" % role)
    return user_id, role
