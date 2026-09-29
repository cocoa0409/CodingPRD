"""Authentication / authorization (PRD 2.1, validations 1-2 and 6)."""
from flask import request

from db import store
from errors import ApiError

ROLES = (
    "LeaseAdministrator",
    "ComplianceOfficer",
    "AssetManager",
    "TenantRep",
    "LenderRep",
)

# convenience role bundles
ALL_ROLES = ROLES
SINGLE_READ_ROLES = ("AssetManager", "LeaseAdministrator", "ComplianceOfficer",
                     "LenderRep", "TenantRep")
LIST_READ_ROLES = ("AssetManager", "LeaseAdministrator", "ComplianceOfficer",
                   "LenderRep")


def caller_id():
    value = request.headers.get("X-User-ID")
    return value.strip() if isinstance(value, str) else None


def caller_role():
    value = request.headers.get("X-User-Role")
    return value.strip() if isinstance(value, str) else None


def authorize(allowed_roles):
    """Rung 1 then rung 2.  Returns (role, user_id)."""
    role = caller_role()
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, caller_id()


def authorize_clock(allowed_roles):
    """PRD 2.1: the clock capability is the sole authentication exception, but
    authorization still applies when a role IS supplied."""
    role = caller_role()
    if role:
        if role not in allowed_roles:
            raise ApiError("ERR_UNAUTHORIZED")
    return role, caller_id()


def tenant_scope_lease(role, user_id, lease):
    """Rung 6 - a TenantRep may only address its own tenant's leases."""
    if role != "TenantRep":
        return
    if not user_id or lease.get("tenant_id") != user_id:
        raise ApiError("ERR_TENANT_SCOPE_FORBIDDEN")


def acting_tenant(role, user_id):
    """The Tenant record behind a TenantRep caller, if any."""
    if role != "TenantRep" or not user_id:
        return None
    return store.tenants.get(user_id)
