"""Auth header extraction and role/ownership checks (PRD section 2.1)."""

from flask import request

from errors import forbidden, not_owner, unauthenticated

ROLES = ("Resident", "Dispatcher", "Technician", "Vendor", "PropertyManager")


def authn():
    """Priority 1: both headers present and role in the declared set."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        unauthenticated()
    return uid, role


def authorize(role, allowed):
    """Priority 2: role permitted on this endpoint."""
    if role not in allowed:
        forbidden()


def require_assigned_party(wo, uid, role):
    """Priority 3 ownership for Technician/Vendor execution endpoints."""
    if (
        wo["assignment_type"] == "IN_HOUSE"
        and role == "Technician"
        and wo["assigned_technician_id"] == uid
    ):
        return
    if (
        wo["assignment_type"] == "VENDOR"
        and role == "Vendor"
        and wo["assigned_vendor_id"] == uid
    ):
        return
    not_owner()
