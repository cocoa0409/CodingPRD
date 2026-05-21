"""Role-based access control helpers."""
from __future__ import annotations

from flask import g, request

from .envelope import err_auth_required, err_forbidden

ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def load_auth() -> None:
    """Populate flask.g with user_id and user_role. Raise on missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in ROLES:
        raise err_auth_required()
    g.user_id = user_id
    g.user_role = user_role


def require_role(*allowed: str) -> None:
    if g.user_role not in allowed:
        raise err_forbidden(f"Role {g.user_role} not permitted")


def is_role(role: str) -> bool:
    return g.user_role == role
