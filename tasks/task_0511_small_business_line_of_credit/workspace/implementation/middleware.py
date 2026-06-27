"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 / §1.7).

Headers: X-User-ID (acting operator), X-User-Role (capacity).
Roles: Underwriter | Servicer | CreditOfficer.

Two endpoints skip auth entirely: merchant registration (POST /merchants) and
the logical-clock control endpoint (POST /_clock/set_current_utc).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"Underwriter", "Servicer", "CreditOfficer"}


def get_identity():
    """Return (user_id, role) from headers. Does NOT validate."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth():
    """Validate auth headers. Returns (user_id, role). Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Enforce that `role` is in `allowed`. Raises ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")


def auth_and_role(allowed):
    """Combined: authenticate then check role. Returns (user_id, role)."""
    user_id, role = require_auth()
    require_role(role, allowed)
    return user_id, role
