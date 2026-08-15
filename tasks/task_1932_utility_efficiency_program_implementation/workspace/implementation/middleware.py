"""Authentication and role-authorization helpers."""

from __future__ import annotations

from flask import request

import errors

VALID_ROLES = {"ProgramManager", "Contractor", "Inspector", "Customer"}


def get_auth():
    """Return (role, user_id). Raise ApiError(401) when missing/empty."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role.strip() == "" or user_id.strip() == "":
        raise errors.unauthenticated()
    return role, user_id


def require_roles(allowed):
    """Verify the request is authenticated and its role is in `allowed`."""
    role, user_id = get_auth()
    if role not in VALID_ROLES or role not in allowed:
        raise errors.unauthorized()
    return role, user_id
