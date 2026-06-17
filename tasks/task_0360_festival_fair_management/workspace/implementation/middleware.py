"""Auth header extraction and RBAC.

Headers (PRD §2.1): X-User-ID, X-User-Role. Roles spelled exactly:
FestivalDirector, BoxOffice, VendorManager, Vendor, GateAttendant.
"""
from flask import request
from errors import err

ROLES = {"FestivalDirector", "BoxOffice", "VendorManager", "Vendor", "GateAttendant"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing/blank (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role must be permitted for this operation."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "role %s is not permitted for this operation" % role)
