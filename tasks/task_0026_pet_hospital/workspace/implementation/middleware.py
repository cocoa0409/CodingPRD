"""Auth middleware — extract X-User-ID / X-User-Role and enforce RBAC."""
from __future__ import annotations

from flask import g, request

from errors import err

VALID_ROLES = {
    "TriageNurse", "DraftingVet", "ReviewingVet", "Pharmacist",
    "Cashier", "OwnerService", "PlatformAdmin",
}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_AUTH_MISSING", "X-User-ID header missing or blank")
    if not role or not role.strip():
        raise err("ERR_AUTH_MISSING", "X-User-Role header missing or blank")
    if role not in VALID_ROLES:
        raise err(
            "ERR_AUTH_INVALID_ROLE",
            f"Unrecognized role: {role}",
        )
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles):
    if getattr(g, "user_role", None) not in allowed_roles:
        raise err(
            "ERR_FORBIDDEN",
            f"Role {getattr(g, 'user_role', None)!r} not permitted for this endpoint",
        )
