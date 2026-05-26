"""Auth header extraction, role checking, request helpers (PRD §2.1)."""
from __future__ import annotations

from typing import Iterable, Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


ALLOWED_ROLES = {"Couple", "GuestSelf", "PlatformIntegration", "PlatformAdmin"}


def _extract_headers():
    """Read X-User-Role / X-User-ID / X-Invitation-Token, validate well-formedness.

    Raises ERR_UNAUTHENTICATED (401) if headers missing or role unknown.
    Stores resolved identity on flask.g.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    invitation_token = request.headers.get("X-Invitation-Token")

    # Both X-User-Role and X-User-ID must be present and non-empty.
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-Role or X-User-ID header")
    if role not in ALLOWED_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, f"Unknown role: {role}")

    g.user_role = role
    g.user_id = user_id
    g.invitation_token = invitation_token


def require_auth(allowed_roles: Iterable[str]):
    """Validate authentication headers AND restrict to the given roles.

    Returns the function; intended to be called at the top of route handlers.
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def current_invitation_token() -> Optional[str]:
    return getattr(g, "invitation_token", None)


def get_json_body() -> dict:
    """Return parsed JSON body; treats missing body as empty dict.

    Does not raise for empty body — many state-machine endpoints have no
    required input. Callers should still validate required fields.
    """
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise APIError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body
