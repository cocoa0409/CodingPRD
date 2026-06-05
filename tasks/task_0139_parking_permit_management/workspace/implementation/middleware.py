"""Auth header extraction and role checking (PRD §2.1 / scaffold §1.4).

Validation priority (PRD §2.9):
  1. ERR_UNAUTHENTICATED (401) — X-User-ID and X-User-Role both present and
     X-User-Role is a recognized role.
  2. ERR_UNAUTHORIZED (403) — the acting role is permitted for this operation.

Both checks run before any existence / state / business evaluation.
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import APIError, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

# The four recognized roles (PRD §2.1).
ALLOWED_ROLES = {"FacilityAdmin", "Motorist", "Merchant", "EnforcementOfficer"}


def _extract_headers() -> None:
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not user_id or not role or role not in ALLOWED_ROLES:
        raise APIError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or unknown X-User-ID / X-User-Role header",
        )

    g.user_role = role
    g.user_id = user_id


def require_auth(allowed_roles: Iterable[str]):
    """Validate auth headers, then restrict to allowed_roles.

    A known-but-unpermitted role surfaces as ERR_UNAUTHORIZED (403).
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(
                ERR_UNAUTHORIZED,
                403,
                f"Role {g.user_role} not permitted for this operation",
            )

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def get_json_body() -> dict:
    """Parse the JSON body. Missing body -> {}; non-object body -> 400."""
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body
