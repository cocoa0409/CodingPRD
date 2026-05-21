"""Authentication / authorization helpers.

The PRD validation pipeline runs header checks first, then role-to-endpoint
authorization. Each route handler explicitly calls `require_role` to check
RBAC after the global header check has run.
"""
from __future__ import annotations

from typing import Iterable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def parse_headers() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise ApiError("ERR_AUTH_REQUIRED")
    return user_id, user_role


def require_role(*allowed: str) -> None:
    if g.user_role not in allowed:
        raise ApiError("ERR_FORBIDDEN")


def is_opaque_role(role: str) -> bool:
    return role in ("CustomerService", "PlatformAdmin")


def require_identity_match(target_id: str) -> None:
    """For roles whose X-User-ID is bound to a real entity, ensure it matches the target id."""
    if is_opaque_role(g.user_role):
        return
    if g.user_id != target_id:
        raise ApiError("ERR_FORBIDDEN")
