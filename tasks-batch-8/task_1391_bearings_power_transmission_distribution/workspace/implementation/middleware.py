"""Auth: X-User-ID / X-User-Role header validation and role gating.

Priority 1: headers present and well-formed -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
Priority 2: role permitted for the endpoint  -> ERR_INSUFFICIENT_PERMISSIONS (403)
"""

import functools

from flask import request

from errors import err

ROLES = {
    "SystemAdmin",
    "PricingAnalyst",
    "ContractAdministrator",
    "CounterSalesRep",
    "BranchManager",
    "OnCallTechnician",
    "WarrantyAnalyst",
    "QualityEngineer",
    "CustomerPlant",
    "ServiceShop",
}
# "Any" is a pseudo-role: never a valid header value.


def auth_context():
    """Validate headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    if role not in ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role is not a recognized role",
        )
    return user_id.strip(), role


def require_roles(*roles):
    """Decorator: priority 1 header check, then priority 2 permission check."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = auth_context()
            if role not in roles:
                raise err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    f"role {role} may not call this endpoint",
                )
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator


def require_any(fn):
    """GET endpoints: any authenticated role may read."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user_id, role = auth_context()
        return fn(user_id, role, *args, **kwargs)

    return wrapper
