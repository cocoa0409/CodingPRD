"""Auth + RBAC (PRD 2.1, scaffold 1.7).

Every request must carry X-User-ID and X-User-Role. Missing/malformed either ->
ERR_UNAUTHENTICATED. Role not permitted for the operation -> ERR_FORBIDDEN.
Authorization is decided purely by role membership; X-User-ID is opaque and is
never matched against any entity id.
"""

from flask import request

from errors import err

VALID_ROLES = {"Allergist", "Pharmacist", "Nurse", "Biller", "FrontDesk"}


def require_auth():
    """Validate the two mandatory headers; return (user_id, role).

    Raises ERR_UNAUTHENTICATED when either header is missing or malformed
    (including an unrecognized role value).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: role must be in the allowed set for this operation."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
