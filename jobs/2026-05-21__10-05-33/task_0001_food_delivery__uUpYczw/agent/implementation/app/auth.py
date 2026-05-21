"""RBAC helpers — header parsing and role gating."""
from __future__ import annotations

from typing import Iterable

from flask import request

from .errors import ApiError


ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def caller():
    """Return (user_id, role). Raises ERR_AUTH_REQUIRED on missing/invalid headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise ApiError("ERR_AUTH_REQUIRED", f"Unknown role: {role}")
    return user_id, role


def require_role(allowed: Iterable[str]):
    """Validate headers and check role membership. Returns (user_id, role)."""
    uid, role = caller()
    if role not in set(allowed):
        raise ApiError("ERR_FORBIDDEN", f"Role {role} not permitted")
    return uid, role
