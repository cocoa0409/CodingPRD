"""Auth header extraction and role checking (SCAFFOLD validations priority 1-3)."""
from flask import request

from errors import unauthenticated, forbidden

ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep", "FieldTechnician")


def get_auth():
    """Return (user_id, role). Raises 401 on missing/invalid headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated("X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise unauthenticated("X-User-Role must be one of: " + ", ".join(ROLES))
    return user_id, role


def require_roles(*allowed):
    """Authenticate and check endpoint role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise forbidden("Role %s is not authorized for this endpoint" % role)
    return user_id, role


def check_facility_ownership(user_id, role, facility_id):
    """Priority-3 ownership: FacilityManager may only act on own facility."""
    if role == "FacilityManager" and facility_id != user_id:
        raise forbidden("FacilityManager may only act on their own facility")
