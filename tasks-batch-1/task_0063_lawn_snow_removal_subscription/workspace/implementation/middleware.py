from flask import request
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"PlatformAdmin", "Customer", "DispatchManager", "CrewLead"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED if missing/unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
