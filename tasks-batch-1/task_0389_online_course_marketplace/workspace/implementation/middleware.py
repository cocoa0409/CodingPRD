"""Auth header extraction and RBAC primitives (PRD §2.1, §2.11).

Headers (authoritative per PRD §2.1):
  X-User-ID   — acting principal id
  X-User-Role — one of: Anonymous, Instructor, Learner, PlatformAdmin

Auth (ERR_UNAUTHENTICATED 401) is checked first; the two registration
endpoints are the only unauthenticated routes. Authorization
(ERR_FORBIDDEN 403) — role permitted + ownership — comes next.
"""
from flask import request

from errors import err

ROLES = {"Anonymous", "Instructor", "Learner", "PlatformAdmin"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the auth headers and return a Principal.

    Raises ERR_UNAUTHENTICATED (401) when either header is missing or the role
    is not a recognized role name.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    return Principal(user_id, role)


def require_roles(principal, *allowed):
    """Authorization role gate. Raises ERR_FORBIDDEN (403) if role not allowed."""
    if principal.role not in allowed:
        raise err("ERR_FORBIDDEN")
