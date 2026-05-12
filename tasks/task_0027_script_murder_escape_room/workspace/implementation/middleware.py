"""Auth header extraction and role checking."""
from flask import request

from db import store
from errors import (
    APIError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    raise_error,
)


VALID_ROLES = {
    "PlatformAdmin",
    "VenueOperator",
    "ScriptAuthor",
    "Host",
    "NPC",
    "Player",
    "ContentModerator",
    "PaymentGateway",
}


def get_user_context() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID", None)
    user_role = request.headers.get("X-User-Role", None)
    if user_id is None or user_role is None:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    user_id = user_id.strip()
    user_role = user_role.strip()
    if not user_id or not user_role:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    if user_role not in VALID_ROLES:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return user_id, user_role


def require_role(*allowed_roles: str):
    user_id, user_role = get_user_context()
    if user_role not in allowed_roles:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS)
    return user_id, user_role


def ensure_role_in(user_role: str, allowed: set[str]):
    if user_role not in allowed:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS)
