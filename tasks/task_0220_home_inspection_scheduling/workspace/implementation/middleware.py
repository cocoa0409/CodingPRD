"""Authentication and RBAC.

Auth headers (PRD §2.1):
  X-User-ID   - acting user id (opaque for Scheduler, entity id for the others)
  X-User-Role - one of: Scheduler, Inspector, Client, Agent

Priority 1 (auth): both headers present and X-User-Role a known role, else
ERR_UNAUTHENTICATED (401).
Priority 2 (authz): acting role permitted for the endpoint, else ERR_FORBIDDEN (403).
"""
from flask import request

import errors

KNOWN_ROLES = {"Scheduler", "Inspector", "Client", "Agent"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the auth headers and return a Caller. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise errors.unauthenticated()
    if role not in KNOWN_ROLES:
        raise errors.unauthenticated("Unknown X-User-Role.")
    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """Enforce RBAC. Raises ERR_FORBIDDEN if caller.role not in allowed_roles."""
    if caller.role not in allowed_roles:
        raise errors.forbidden()
