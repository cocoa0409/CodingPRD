"""Auth header extraction and role checking.

Headers: X-User-ID, X-User-Role. Roles: Member, Volunteer, ProgramAdmin.
Band order: 1 auth presence -> 2 role permission (12 ownership, 13 OCC later).
"""

from flask import request
from errors import unauthenticated, unauthorized_role

ROLES = {"Member", "Volunteer", "ProgramAdmin"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Band 1 + 2: authenticate and check role permission."""
    user_id, role = get_auth()
    if role not in roles:
        raise unauthorized_role()
    return user_id, role
