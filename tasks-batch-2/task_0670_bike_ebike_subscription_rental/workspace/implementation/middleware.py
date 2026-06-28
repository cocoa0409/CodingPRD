"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 priorities 1-2)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"Subscriber", "FleetManager", "FieldTech", "OpsAdmin", "Anonymous"}
ENTITY_BACKED_ROLES = {"Subscriber", "FleetManager"}


def get_identity():
    """Return (user_id, role) from headers (may be None)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth():
    """Priority 1: X-User-ID and X-User-Role present and X-User-Role a known role.
    Returns (user_id, role)."""
    user_id, role = get_identity()
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    return user_id, role


def require_role(allowed_roles):
    """Authenticate then check the acting role is permitted (priority 2 / 403).
    Returns (user_id, role)."""
    user_id, role = require_auth()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role is not permitted to perform this operation.")
    return user_id, role
