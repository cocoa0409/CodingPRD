"""Auth header extraction + role authorization (PRD §2.1, §2.6 priorities 1-2)."""
from flask import request

import errors

KNOWN_ROLES = {"SystemAdmin", "Dispatcher", "Agent", "Citizen", "Anonymous"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and role known.

    Returns a Principal or raises ERR_UNAUTHENTICATED (401).
    Callers for the two exempt endpoints (POST /citizens, _clock/*) handle auth
    themselves and do not invoke this.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return Principal(user_id, role)


def authorize(principal, allowed_roles):
    """Priority 2: acting role is permitted for this endpoint, else ERR_FORBIDDEN_ROLE (403)."""
    if principal.role not in allowed_roles:
        raise errors.forbidden_role()
