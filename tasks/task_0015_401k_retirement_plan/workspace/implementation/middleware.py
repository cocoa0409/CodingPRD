"""Auth header extraction + role checking per PRD §2.1."""

from __future__ import annotations

from functools import wraps

from flask import g, request

from errors import APIError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED


VALID_ROLES = {"PlanAdmin", "Participant", "Custodian"}


def auth_required(*allowed_roles: str):
    """Decorator: require X-User-ID and X-User-Role, restrict to `allowed_roles`.

    `allowed_roles` lists the roles permitted to call this endpoint. If empty,
    any authenticated role passes.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role:
                raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role")
            if user_role not in VALID_ROLES:
                raise APIError(ERR_UNAUTHENTICATED, 401, f"Unknown role '{user_role}'")
            if allowed_roles and user_role not in allowed_roles:
                raise APIError(ERR_FORBIDDEN, 403, f"Role '{user_role}' not permitted")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def assert_participant_owns(participant_id: str) -> None:
    """If acting role is Participant, ensure the resource's participant_id == X-User-ID."""
    if g.user_role == "Participant" and g.user_id != participant_id:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only access own resources")
