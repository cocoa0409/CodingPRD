"""Auth header extraction, role checking (PRD §2.1).

Validation priority (PRD §2.9 / scaffold §1.4):
  1. ERR_UNAUTHENTICATED (401) — both X-User-ID and X-User-Role present and
     X-User-Role is a known role
  2. ERR_FORBIDDEN_ROLE (403) — recognised role authorised for this endpoint
"""
from __future__ import annotations

from typing import Iterable, Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST


ALLOWED_ROLES = {"Anonymous", "Fan", "PromoterAdmin", "GateScanner"}


def _extract_headers() -> None:
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-Role or X-User-ID header")
    if role not in ALLOWED_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, f"Unknown role: {role}")

    g.user_role = role
    g.user_id = user_id


def require_auth(allowed_roles: Iterable[str]):
    """Validate headers + restrict to the given roles.

    Returns a no-arg callable invoked at the top of each route handler.
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this endpoint")

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def get_json_body() -> dict:
    """Return parsed JSON body; missing body becomes {}.

    Raises ERR_INVALID_REQUEST if the body is present but is not a JSON object.
    """
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body
