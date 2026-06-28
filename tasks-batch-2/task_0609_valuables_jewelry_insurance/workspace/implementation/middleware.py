"""Auth header extraction and role checking (PRD §2.1, §2.10).

Every request must carry X-User-ID and X-User-Role. Missing/malformed ->
ERR_UNAUTHENTICATED (401). Role not permitted, or an entity-backed role acting
on a resource it does not own -> ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err

ROLES = {"Underwriter", "ClaimsAdjuster", "Appraiser", "Policyholder", "RepairShop"}


def get_identity():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED if absent/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err("ERR_UNAUTHENTICATED", "Empty X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """403 if the well-formed role is not permitted for this endpoint."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s not permitted for this operation" % role)
