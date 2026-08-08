"""Authentication, role authorisation and ownership (PRD 2.1, 2.7 rungs 1/2/4)."""

from flask import request

import errors
from errors import ApiError

ROLES = ("Patient", "Provider", "Coach", "PharmacyOperator", "BillingAdmin", "PlatformAdmin")
ANY_ROLE = ROLES


def authenticate():
    """Rung 1: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED)
    return user_id, role


def authorize(role, allowed_roles):
    """Rung 2: the acting role appears in the endpoint's role list."""
    if role not in allowed_roles:
        raise ApiError(errors.ERR_UNAUTHORIZED)


def guard(allowed_roles):
    """Run rungs 1 and 2 and hand back the caller identity."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def require_owner(condition):
    """Rung 4: ownership on the six guarded operations of PRD 2.1."""
    if not condition:
        raise ApiError(errors.ERR_UNAUTHORIZED)
