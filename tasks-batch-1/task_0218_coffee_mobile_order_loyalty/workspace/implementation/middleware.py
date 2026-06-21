"""Auth header extraction and role checking.

PRD §2.1: every request other than member registration must carry X-User-ID and
X-User-Role. Missing either header (or an unrecognized role) -> ERR_UNAUTHENTICATED.
Role not permitted, or ownership check fails -> ERR_FORBIDDEN.
Recognized roles, spelled precisely: Anonymous, Member, StoreOperator, PlatformAdmin.
"""
from flask import request

import errors

VALID_ROLES = {"Anonymous", "Member", "StoreOperator", "PlatformAdmin"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the two auth headers. Returns Principal or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return Principal(user_id, role)


def require_roles(principal, allowed_roles):
    """ERR_FORBIDDEN if the principal's role is not in allowed_roles."""
    if principal.role not in allowed_roles:
        raise errors.forbidden()


def require_owner(principal, owner_id):
    """For entity_backed Member: X-User-ID must match the resource owner FK.
    PRD §2.1. StoreOperator/PlatformAdmin are role-authorized (no ownership match)."""
    if principal.role == "Member" and principal.user_id != owner_id:
        raise errors.forbidden()
