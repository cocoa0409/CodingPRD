"""Auth header extraction and role checking."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

KNOWN_ROLES = {"Client", "Therapist", "ClinicalAdmin", "BillingAdmin"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED if missing/unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return user_id, role


def require_role(role, allowed):
    """role must be in the allowed set, else ERR_UNAUTHORIZED."""
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation")
