"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.9, SCAFFOLD §1.7).

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Recognized roles (exactly): GrantWriter, FinanceOfficer, ProgramManager,
AgencyOfficer, Auditor, Anonymous.

Validation order (PRD §3.9): authentication (401) before authorization (403).
"""
from functools import wraps

from flask import request

import errors

RECOGNIZED_ROLES = {
    "GrantWriter",
    "FinanceOfficer",
    "ProgramManager",
    "AgencyOfficer",
    "Auditor",
    "Anonymous",
}


def get_identity():
    """Return (user_id, role) from headers, raising ERR_UNAUTHENTICATED when
    either header is missing or the role is not recognized (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator enforcing authentication then role authorization.

    The acting role must be one of allowed_roles, else ERR_FORBIDDEN (403).
    Anonymous is never in any allowed set, so it is always forbidden once it
    authenticates — matching PRD §2.1 ("no permitted operations").

    The wrapped view receives keyword args user_id and role.
    """
    allowed = set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                raise errors.forbidden()
            return view(*args, user_id=user_id, role=role, **kwargs)

        return wrapper

    return decorator
