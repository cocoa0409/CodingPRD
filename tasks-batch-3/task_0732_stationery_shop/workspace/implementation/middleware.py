"""Auth header extraction and role enforcement."""

from flask import request

import errors


VALID_ROLES = {"Customer", "Designer", "ShopAdmin"}


def get_auth():
    """Return (user_id, role) — raises ERR_UNAUTHENTICATED if invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES:
        errors.raise_error(errors.ERR_UNAUTHENTICATED, "missing or invalid X-User-Role")
    if user_id is None or user_id == "":
        errors.raise_error(errors.ERR_UNAUTHENTICATED, "missing X-User-ID")
    return user_id, role


def require_roles(user_role: str, allowed: list[str]):
    if user_role not in allowed:
        errors.raise_error(errors.ERR_UNAUTHORIZED, "role not permitted for this endpoint")


def require_owner(user_id: str, owner_id: str):
    if user_id != owner_id:
        errors.raise_error(errors.ERR_UNAUTHORIZED, "resource owner mismatch")
