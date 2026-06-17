"""Auth header extraction and role authorisation (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The four recognised roles
are spelled exactly: ShopManager, ServiceAdvisor, Technician, FleetManager.
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


VALID_ROLES = {"ShopManager", "ServiceAdvisor", "Technician", "FleetManager"}


def require_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED (401) if a header is
    missing or malformed (blank, or an unrecognised role)."""
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not isinstance(uid, str):
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing or malformed X-User-Role header")
    return uid, role


def require_role(*allowed_roles):
    """Authenticate (401) then verify role membership (403)."""
    uid, role = require_auth()
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, f"role {role!r} not permitted for this operation")
    return uid, role
