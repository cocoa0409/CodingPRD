"""Auth + RBAC (PRD 2.1, scaffold §1.4 priority 1-2 and §1.7).

PRD 2.1: every request must carry X-User-ID and X-User-Role. If either header is
missing, or X-User-Role is not one of the recognized role names, the request is
rejected with ERR_UNAUTHENTICATED. When the headers are well-formed but the named
role is not permitted, the request is rejected with ERR_FORBIDDEN_ROLE.

The four recognized roles: Registrar, FinancialAidOfficer, Instructor, Student.
"""
from functools import wraps

from flask import g, request

import errors

VALID_ROLES = {"Registrar", "FinancialAidOfficer", "Instructor", "Student"}


def extract_auth():
    """Priority 1 (PRD 2.1): establish auth context on every request."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise errors.unauthenticated()
    if not user_role or user_role not in VALID_ROLES:
        raise errors.unauthenticated()
    g.user_id = user_id
    g.user_role = user_role


def require(*allowed_roles):
    """Priority 2: enforce that the caller's role is among allowed_roles."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.get("user_role") not in allowed:
                raise errors.forbidden_role()
            return fn(*args, **kwargs)
        return wrapper
    return deco
