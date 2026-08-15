"""Auth context (validation tier 1) and RBAC (tier 2) per PRD section 2.1.

Headers: X-User-ID (acting user) and X-User-Role (one of the four declared
roles). Tenant is entity-backed: X-User-ID is the acting Tenant record's id.
The other three roles carry opaque operator identifiers.
"""

from flask import request

import errors

ROLES = {"PropertyManager", "LeasingAgent", "Tenant", "SystemOps"}

PM = {"PropertyManager"}
AGENT = {"LeasingAgent"}
OPS = {"SystemOps"}
ALL = ROLES


def current_user():
    """Return (user_id, role). Tier 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(
            errors.ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and the role must be "
            "one of PropertyManager, LeasingAgent, Tenant, SystemOps.",
        )
    return user_id, role


def require_role(role, allowed):
    """Tier 2: role permitted to call this endpoint."""
    if role not in allowed:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "Role %s is not permitted to call this endpoint." % role,
        )


def require_owns_lease(user_id, lease):
    """Tenant ownership check: the lease's primary_tenant_id must be the caller."""
    if lease["primary_tenant_id"] != user_id:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may act only on their own lease graph.",
        )
