"""Auth header extraction, role checking, renter ownership (PRD §2.1, §2.11)."""

from functools import wraps

from flask import request

import errors

ROLES = ("Renter", "DockStaff", "FleetManager", "Mechanic")


def auth_context():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED when headers missing
    or the role is not one of the four declared roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.err(
            errors.ERR_UNAUTHENTICATED,
            "Missing or unknown X-User-Role / X-User-ID headers",
        )
    return user_id, role


def require_roles(*allowed):
    """Decorator: validates auth headers (401), then role membership (403).
    Passes (user_id, role) as keyword args to the wrapped view."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = auth_context()
            if role not in allowed:
                errors.err(
                    errors.ERR_FORBIDDEN,
                    f"Role {role} is not authorized for this endpoint",
                )
            kwargs["user_id"] = user_id
            kwargs["role"] = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def check_renter_owner(owner_id, user_id, role):
    """Renter role may only act on own resources (403 ERR_NOT_RESOURCE_OWNER).
    Opaque-operator roles are never ownership-checked."""
    if role == "Renter" and owner_id != user_id:
        errors.err(
            errors.ERR_NOT_RESOURCE_OWNER,
            "Renter may only act on their own resources",
        )
