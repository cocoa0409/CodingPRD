"""Auth header extraction and role checking (PRD §2.1, §2.9).

Two mandatory headers per request:
  X-User-ID   — acting user id (entity id for Client/Tasker, opaque for operators)
  X-User-Role — one of Client | Tasker | Dispatcher | TrustSafetyOfficer
"""
from flask import request

import errors
from errors import err

VALID_ROLES = {"Client", "Tasker", "Dispatcher", "TrustSafetyOfficer"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Validate the two auth headers. Priority 1 — ERR_MISSING_OR_INVALID_USER_CONTEXT."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT, "Missing or invalid X-User-ID")
    if not role or role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT, "Missing or invalid X-User-Role")
    return Caller(user_id.strip(), role)


def require_roles(caller, allowed_roles):
    """Priority 2 — ERR_FORBIDDEN_ROLE if the caller's role is not permitted."""
    if caller.role not in allowed_roles:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
