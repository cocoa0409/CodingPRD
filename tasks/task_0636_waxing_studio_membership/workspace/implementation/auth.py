"""Authentication and role extraction (PRD 2.1).

Every request must be authenticated through two mandatory HTTP headers:
X-User-ID and X-User-Role. The platform recognizes exactly four roles:
StudioAdmin, FrontDesk, Technician, Member.
"""
from flask import request

from errors import err

ROLES = {"StudioAdmin", "FrontDesk", "Technician", "Member"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """PRD 2.1: missing header or unknown role -> ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    return Principal(user_id, role)


def require_roles(principal, allowed):
    """PRD 2.1: role not permitted for the operation -> ERR_UNAUTHORIZED."""
    if principal.role not in allowed:
        raise err("ERR_UNAUTHORIZED", "role %s not permitted" % principal.role)
