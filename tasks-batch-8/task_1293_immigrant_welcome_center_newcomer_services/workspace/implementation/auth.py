"""Authentication / role helpers.

Headers: X-User-ID + X-User-Role. Six declared roles. Missing headers or an
unrecognized role -> ERR_UNAUTHENTICATED (401). A valid role that is not
permitted on an endpoint -> ERR_FORBIDDEN (403).
"""
from flask import request

from errors import unauthenticated, forbidden, not_found
import db

ROLES = {"CenterAdmin", "CaseManager", "IntakeSpecialist",
         "PartnerOrg", "Client", "FunderAuditor"}

STAFF_ROLES = {"CenterAdmin", "CaseManager", "IntakeSpecialist"}


def actor():
    """Return (user_id, role); raise 401 when headers are missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require(*roles):
    """Authenticate, then enforce endpoint role membership."""
    user_id, role = actor()
    if role not in roles:
        raise forbidden()
    return user_id, role


def get_or_404(collection, entity_id, label=None):
    ent = db.get(collection, entity_id)
    if ent is None:
        raise not_found(f"{label or collection} not found: {entity_id}")
    return ent


def staff_clearance(user_id):
    """Clearance level of the acting staff member (None when unknown)."""
    staff = db.get("staff", user_id)
    if staff is None:
        return None
    return staff.get("clearance_level")
