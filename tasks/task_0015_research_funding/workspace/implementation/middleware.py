"""Auth header extraction and role checking."""

from functools import wraps

from flask import g, request

from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_USER_CONTEXT,
    raise_error,
)


VALID_ROLES = {
    "PrincipalInvestigator",
    "DepartmentApprover",
    "FinanceOfficer",
    "ResearchAdmin",
    "AuditOfficer",
    "PeerReviewer",
    "TestDriver",
}


def require_auth():
    """Extract and validate X-User-ID / X-User-Role headers."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(ERR_MISSING_USER_CONTEXT, "X-User-ID and X-User-Role headers required")
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles):
    """Decorator factory: require the caller's role to be in allowed_roles.

    Use 'Any' as a special token to allow any authenticated role.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = getattr(g, "user_role", None)
            if role is None:
                raise_error(ERR_MISSING_USER_CONTEXT, "auth missing")
            if "Any" in allowed_roles:
                if role not in VALID_ROLES:
                    raise_error(ERR_INSUFFICIENT_PERMISSIONS, "role not permitted")
            else:
                if role not in allowed_roles:
                    raise_error(ERR_INSUFFICIENT_PERMISSIONS, f"role {role} not permitted")
            return fn(*args, **kwargs)

        return wrapper

    return deco
