"""Auth header extraction and role checking."""
from flask import request

import errors
from errors import err

ROLES = {"CityRegistrar", "TaxOfficer", "Host", "Platform"}


def get_auth():
    """Return (user_id, role) after validating presence and role validity.
    Raises ERR_UNAUTHENTICATED (401) on missing/invalid headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_UNAUTHORIZED (403) if role not in allowed set."""
    if role not in allowed:
        raise err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")
