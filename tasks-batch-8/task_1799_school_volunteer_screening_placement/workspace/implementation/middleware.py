"""Auth header extraction and role checking per PRD §2.1 and scaffold §1.4 p1/p2."""

from flask import request

import db
from errors import unauthenticated, forbidden


ROLES = ("DistrictCoordinator", "CampusAdmin", "Volunteer")


def get_auth():
    """Validate auth headers. Returns (role, user_id).

    p1: X-User-Role and X-User-ID headers present; X-User-Role is a declared role.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise unauthenticated()
    if role not in ROLES:
        raise unauthenticated()
    if not isinstance(user_id, str) or not user_id.strip():
        raise unauthenticated()
    return role, user_id


def require_roles(*allowed):
    """Validate auth and ensure the caller's role is in allowed (p2)."""
    role, user_id = get_auth()
    if role not in allowed:
        raise forbidden()
    return role, user_id


def check_volunteer_ownership(role, user_id, volunteer_id):
    """For Volunteer role, X-User-ID must equal the target volunteer id (p2)."""
    if role == "Volunteer" and user_id != volunteer_id:
        raise forbidden()
