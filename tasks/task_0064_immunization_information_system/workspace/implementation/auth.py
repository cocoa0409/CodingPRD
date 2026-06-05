from flask import request
import errors
from errors import err

VALID_ROLES = {"ImmunizationRegistrar", "RecordsClerk", "Provider"}


def get_identity():
    """Authenticate: returns (user_id, role) or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation.")
