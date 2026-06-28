"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priority 1-2).

Headers (PRD §2.1):
  X-User-ID   : acting user identifier (opaque for 5 roles; the Account.id for AccountHolder)
  X-User-Role : one of {PlatformAdmin, IntakeClerk, FeeAnalyst, RunnerDispatcher,
                LienOfficer, AccountHolder}

Auth (priority 1): both headers present and X-User-Role a known role, else
                   ERR_UNAUTHENTICATED (401).
RBAC (priority 2): acting role must be permitted for the operation, else
                   ERR_FORBIDDEN_ROLE (403).
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {
    "PlatformAdmin",
    "IntakeClerk",
    "FeeAnalyst",
    "RunnerDispatcher",
    "LienOfficer",
    "AccountHolder",
}


def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    # Both headers must be present; role must be a recognized role name.
    if user_id is None or user_id == "" or role is None or role not in VALID_ROLES:
        raise errors.unauthenticated()
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden_role()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
