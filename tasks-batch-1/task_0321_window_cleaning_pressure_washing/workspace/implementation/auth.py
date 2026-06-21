"""Authentication header extraction and RBAC (PRD §2.1).

Auth headers (PRD §2.1):
  * X-User-ID    — acting user id (for Customer this is the Account id)
  * X-User-Role  — one of Customer, Dispatcher, FieldCrew, Billing

Missing/blank either header -> ERR_UNAUTHENTICATED.
Role not permitted for the operation -> ERR_UNAUTHORIZED.
"""
from flask import request

from errors import err

ROLES = {"Customer", "Dispatcher", "FieldCrew", "Billing"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when either header is
    missing or blank. An unrecognized role value is treated as not-permitted by
    the per-endpoint role check (it simply won't be in the allowed set)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    return user_id.strip(), role.strip()


def require_roles(allowed_roles):
    """Authenticate then authorize against `allowed_roles`.

    Returns (user_id, role). Auth (401) is always checked before authz (403)
    per the validation priority order.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s not permitted for this operation" % role)
    return user_id, role
