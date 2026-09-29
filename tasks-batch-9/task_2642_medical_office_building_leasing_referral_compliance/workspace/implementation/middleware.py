"""Authentication and role-based access control (PRD Section 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "PortfolioAdmin",
    "LeasingAgent",
    "ComplianceOfficer",
    "PropertyManager",
    "FacilitiesEngineer",
    "TenantPortalUser",
)

ALL_ROLES = ROLES
TENANT_PORTAL = "TenantPortalUser"


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(*allowed_roles):
    """Rung 1 (authentication) then rung 2 (authorisation) of PRD Section 2.8."""
    allowed = tuple(allowed_roles) if allowed_roles else ALL_ROLES

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role '%s' may not perform this operation." % role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return g.get("user_id")


def acting_role():
    return g.get("role")


def is_portal_user():
    return g.get("role") == TENANT_PORTAL


def require_tenant_scope(tenant_id):
    """Rung 9: a TenantPortalUser may only reach rows owned by its own tenant.
    A mismatch is ERR_UNAUTHORIZED, never a 404."""
    if is_portal_user() and acting_user_id() != tenant_id:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "A tenant portal user may only access its own tenant's resources.",
        )
