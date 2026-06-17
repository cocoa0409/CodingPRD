"""Auth header extraction and role checking (PRD §2.1).

Validation priority order (scaffold §1.4):
  1 - ERR_UNAUTHENTICATED  - X-User-Role and X-User-ID both present and X-User-Role recognized
  2 - ERR_UNAUTHORIZED     - acting role permitted for the operation
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import APIError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST


# PRD §2.1: exactly four roles, spelled as written.
KNOWN_ROLES = {"Customer", "ServiceAdvisor", "Technician", "InventoryManager"}


def _extract_headers() -> None:
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or not user_id or role not in KNOWN_ROLES:
        raise APIError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-Role and X-User-ID headers required; X-User-Role must be a recognized role",
        )

    g.user_role = role
    g.user_id = user_id


def require_auth(allowed_roles: Iterable[str]):
    """Return a no-arg callable enforcing priorities 1/2.

    Missing/unknown role -> ERR_UNAUTHENTICATED (401).
    Known but not permitted -> ERR_UNAUTHORIZED (403).
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(
                ERR_UNAUTHORIZED,
                403,
                f"Role {g.user_role} not permitted for this endpoint",
            )

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def get_json_body() -> dict:
    """Return parsed JSON body. Missing body becomes an empty dict.

    Raises ERR_INVALID_REQUEST if body is present but is not a JSON object.
    """
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return body
