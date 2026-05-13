"""Auth header extraction and RBAC helpers.

PRD §2.1: every request carries `X-User-ID` and `X-User-Role`.

If either header is missing/blank we raise ERR_MISSING_AUTH (401).
If the role is not one of the four enumerated values we raise
ERR_FORBIDDEN_ROLE (403). If the role IS enumerated but is not on the
allow-list for the endpoint (or fails an ownership check), we also raise
ERR_FORBIDDEN_ROLE.
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_AUTH,
    raise_err,
)

VALID_ROLES = {"Rider", "Operator", "FieldStaff", "Admin"}


def authenticate() -> None:
    """Pull X-User-ID and X-User-Role headers; populate `g`."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_MISSING_AUTH, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise_err(ERR_FORBIDDEN_ROLE, f"Role '{role}' is not a recognised role")
    g.user_id = user_id
    g.user_role = role


def require_role(*allowed_roles: str) -> None:
    """Reject the request if g.user_role is not in allowed_roles."""
    if g.user_role not in allowed_roles:
        raise_err(
            ERR_FORBIDDEN_ROLE,
            f"Role '{g.user_role}' is not permitted on this endpoint",
        )


def require_rider_owner(rider_id: str) -> None:
    """When the actor is Rider, the X-User-ID must match the resource owner."""
    if g.user_role == "Rider" and g.user_id != rider_id:
        raise_err(
            ERR_FORBIDDEN_ROLE,
            "Rider may only act on their own resource",
        )
