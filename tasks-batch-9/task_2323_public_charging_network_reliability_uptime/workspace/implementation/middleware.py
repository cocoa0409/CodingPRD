"""Header authentication and role authorisation (PRD §2.1, §2.11 steps 1-2)."""
from functools import wraps

from flask import request, g

from errors import err

ROLES = (
    "NetworkOperator",
    "FieldTechnician",
    "ComplianceAuditor",
    "ProgramAdministrator",
    "HostSiteManager",
    "CustomerSupportAgent",
)

ANY_ROLE = ROLES


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(allowed_roles):
    if g.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % g.role)


def endpoint(*allowed_roles):
    """Decorator running §2.11 step 1 then step 2."""
    roles = allowed_roles if allowed_roles else ANY_ROLE

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def require_role_for_leg(role):
    """Sub-selector leg restrictions (e.g. only a ComplianceAuditor may send the
    DRAFT revert leg).  Rejected with ERR_UNAUTHORIZED."""
    if g.role != role:
        raise err("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % g.role)


def current_user_id():
    return g.user_id


def current_role():
    return g.role
