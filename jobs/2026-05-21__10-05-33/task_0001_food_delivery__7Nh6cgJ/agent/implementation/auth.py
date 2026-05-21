"""RBAC headers + role-to-endpoint authorization."""

from __future__ import annotations

from typing import Iterable

from flask import request

from errors import APIError

ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def get_actor() -> tuple[str, str]:
    """Return (user_id, role); raises ERR_AUTH_REQUIRED if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise APIError("ERR_AUTH_REQUIRED")
    return user_id, role


def require_role(allowed: Iterable[str]) -> tuple[str, str]:
    user_id, role = get_actor()
    if role not in allowed:
        raise APIError("ERR_FORBIDDEN")
    return user_id, role
