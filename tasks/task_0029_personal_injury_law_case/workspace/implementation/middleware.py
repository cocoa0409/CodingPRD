"""Auth header extraction, role checking (PRD §2.1, §2.9).

Two endpoints are public and skip auth entirely:
  - POST /clients/register
  - POST /_clock/set_current_utc  (PlatformAdmin endpoint — caller may
    still send X-User-Role; if absent, the endpoint runs unauthenticated.)

Per PRD §2.1, every other request must carry both X-User-ID and X-User-Role.
A missing X-User-Role yields ERR_MISSING_AUTH (401); an X-User-Role that is
not authorized for the endpoint yields ERR_FORBIDDEN_ROLE (403).

The scaffold validation table is explicit that ERR_MISSING_AUTH is keyed on
X-User-Role presence (priority 1, category=auth). Path/FK existence
(priorities 3-4) runs only after auth+authorization passes.
"""
from __future__ import annotations

from typing import Iterable, Optional
from flask import request, g

from errors import (
    APIError,
    ERR_MISSING_AUTH,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
)


ALLOWED_ROLES = {
    "Anonymous",
    "Paralegal",
    "Attorney",
    "ManagingPartner",
    "PlatformAdmin",
}


def _extract_headers(allow_anonymous: bool = False) -> None:
    """Validate auth headers, stash identity on flask.g.

    If allow_anonymous=True, an absent X-User-Role is acceptable and the
    request runs as Anonymous (used by /clients/register).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role:
        if allow_anonymous:
            g.user_role = "Anonymous"
            g.user_id = user_id or ""
            return
        raise APIError(ERR_MISSING_AUTH, 401, "Missing X-User-Role header")

    if role not in ALLOWED_ROLES:
        # Unknown roles are not in the role matrix -> forbidden.
        raise APIError(ERR_FORBIDDEN_ROLE, 403, f"Unknown role: {role}")

    g.user_role = role
    g.user_id = user_id or ""


def require_auth(allowed_roles: Iterable[str], allow_anonymous: bool = False):
    """Return a guard callable for routes.

    `allowed_roles` enumerates the roles permitted for this endpoint.
    If `allow_anonymous` is True, requests without X-User-Role are
    accepted as the Anonymous role; otherwise they are rejected with
    ERR_MISSING_AUTH.
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers(allow_anonymous=allow_anonymous)
        if g.user_role not in allowed_set:
            raise APIError(
                ERR_FORBIDDEN_ROLE,
                403,
                f"Role {g.user_role} not permitted for this endpoint",
            )

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def get_json_body() -> dict:
    """Return the parsed JSON body; missing body becomes an empty dict.

    Raises ERR_INVALID_REQUEST if the body is present but not a JSON object.
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
