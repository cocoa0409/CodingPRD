"""Authentication / RBAC primitives — header parsing + role helpers."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import request

from .errors import APIError, err_auth_required, err_forbidden

# Canonical role spelling per PRD §2.1.
ROLE_PI = "PrincipalInvestigator"
ROLE_IRB = "IRBReviewer"
ROLE_COORD = "StudyCoordinator"
ROLE_PARTICIPANT_SELF = "Participant_self"

ALL_ROLES = {ROLE_PI, ROLE_IRB, ROLE_COORD, ROLE_PARTICIPANT_SELF}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    """Extract and validate the X-User-ID / X-User-Role headers. Raises ERR_AUTH_REQUIRED."""
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_auth_required(
            f"Headers {HEADER_USER_ID} and {HEADER_USER_ROLE} are required"
        )
    if user_role not in ALL_ROLES:
        raise err_auth_required(f"Unknown role: {user_role}")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
    """Decorator: validate auth headers AND check role is in `allowed`. Order: AUTH → FORBIDDEN."""
    allowed_set = set(allowed)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_caller()
            if user_role not in allowed_set:
                raise err_forbidden(
                    f"Role '{user_role}' is not authorized for this endpoint"
                )
            kwargs["_caller_id"] = user_id
            kwargs["_caller_role"] = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def enforce_self_ownership(participant_id_param: str, caller_id: str, caller_role: str) -> None:
    """For Participant_self callers, the path-bound participant_id MUST equal X-User-ID."""
    if caller_role == ROLE_PARTICIPANT_SELF and participant_id_param != caller_id:
        raise err_forbidden(
            "Participant_self may only access their own participant resources"
        )
