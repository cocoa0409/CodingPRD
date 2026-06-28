"""Auth header extraction and role checking (PRD §2.1, validations priority 1-2).

Headers (PRD §2.1):
  X-User-ID   : the acting user identifier (mandatory). When X-User-Role is
                Employee, this is the id of the acting Employee entity; for the
                other roles it is an opaque operator identifier.
  X-User-Role : one of {BenefitsAdmin, ClaimsAdjuster, Employee, Payroll, System}.

Auth (priority 1): both headers must be present and well-formed, else
                   ERR_MISSING_USER_CONTEXT (401).
RBAC (priority 2): role must be permitted for the operation, else
                   ERR_FORBIDDEN_ROLE (403).
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"BenefitsAdmin", "ClaimsAdjuster", "Employee", "Payroll", "System"}


def authenticate():
    """Validate X-User-ID and X-User-Role; populate g.user_role / g.user_id.

    A request missing either header, or carrying a malformed value, is rejected
    with ERR_MISSING_USER_CONTEXT (PRD §2.1).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role.strip() == "" or role not in VALID_ROLES:
        raise errors.missing_user_context()
    if user_id is None or user_id.strip() == "":
        raise errors.missing_user_context()
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    """Decorator: authenticate first (priority 1), then enforce RBAC (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden_role()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
