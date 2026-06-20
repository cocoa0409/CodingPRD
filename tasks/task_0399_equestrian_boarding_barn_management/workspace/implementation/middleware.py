"""Auth header extraction and role checking (PRD §2.1).

Every request must be authenticated through two mandatory HTTP headers:
  X-User-ID   — identifies the acting user
  X-User-Role — declares the capacity in which they act
If either header is missing or malformed -> ERR_MISSING_USER_CONTEXT (401).
The system recognizes exactly four roles, spelled precisely:
  BarnManager, Owner, Instructor, ServiceProvider.
"""
from flask import request

from errors import err

VALID_ROLES = {"BarnManager", "Owner", "Instructor", "ServiceProvider"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Extract & validate the caller. Raises ERR_MISSING_USER_CONTEXT on bad auth."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_USER_CONTEXT", "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in VALID_ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "Malformed X-User-ID or X-User-Role header")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """ERR_FORBIDDEN_ROLE if caller.role not in allowed_roles."""
    if caller.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % caller.role)
