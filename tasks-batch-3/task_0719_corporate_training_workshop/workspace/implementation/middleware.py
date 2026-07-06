from flask import request
from errors import err

VALID_ROLES = {"ProgramDesigner", "SchedulingCoordinator", "Facilitator", "Learner", "FinanceManager"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if headers missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require(allowed_roles):
    """Authenticate then authorize. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
    return user_id, role
