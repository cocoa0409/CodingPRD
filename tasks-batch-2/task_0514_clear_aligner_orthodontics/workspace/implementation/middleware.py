"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 priorities 1-2, §1.7).

Headers: X-User-ID and X-User-Role. Both must be present (ERR_UNAUTHENTICATED,
401) before authorization. Role must be permitted for the endpoint
(ERR_UNAUTHORIZED, 403). Authentication is always checked before authorization.
"""
from flask import request

from errors import err

VALID_ROLES = {"Patient", "Clinician", "ManufacturingOps", "BillingAdmin"}


def get_auth():
    """Return (user_id, role) after validating both headers are present and the
    role is one of the four recognized roles. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        # An unrecognized role cannot be authorized for any endpoint.
        raise err("ERR_UNAUTHENTICATED", "Unrecognized role.")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED",
                  "Role %s is not permitted for this endpoint." % role)
