"""Auth header extraction and RBAC enforcement (PRD §2.1).

Two mandatory headers on every request except the liveness probe:
  X-User-ID    — opaque operator identifier (never a FK to any entity)
  X-User-Role  — one of PlatformAdmin | BillingClerk | Attorney
"""

from flask import request

import errors

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_BILLING_CLERK = "BillingClerk"
ROLE_ATTORNEY = "Attorney"
VALID_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}


def authenticate():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED when a header is
    missing/blank, or when the role is not one of the three recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        # An unrecognized role value is not an authenticated capacity.
        raise errors.unauthenticated("Unrecognized X-User-Role value.")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if the authenticated role is not in `allowed`."""
    if role not in allowed:
        raise errors.forbidden_role()
