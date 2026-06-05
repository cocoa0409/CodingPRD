"""Auth header extraction and role checking (PRD §2.1).

Validation priority order (PRD §2.11):
  100 - ERR_UNAUTHENTICATED - X-User-Role and X-User-ID both present
  110 - ERR_FORBIDDEN       - Caller's role permits this endpoint
  115 - ERR_FORBIDDEN       - When role==Therapist, X-User-ID names an existing
                              Therapist row (entity-backed identity check)
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

import db
from errors import APIError, ERR_FORBIDDEN, ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED


# PRD §2.1: exactly five roles, spelled as written.
KNOWN_ROLES = {
    "PlatformAdmin",
    "CaseManager",
    "Therapist",
    "BillingClerk",
    "VAReferralCoordinator",
}


def _extract_headers() -> None:
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or not user_id:
        raise APIError(
            ERR_UNAUTHENTICATED, 401, "X-User-Role and X-User-ID headers required"
        )

    g.user_role = role
    g.user_id = user_id


def require_auth(allowed_roles: Iterable[str]):
    """Return a no-arg callable enforcing PRD §2.11 priorities 100/110/115.

    Unknown / unauthorized roles surface ERR_FORBIDDEN. When the caller's role
    is Therapist, X-User-ID must name an existing Therapist row.
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(
                ERR_FORBIDDEN,
                403,
                f"Role {g.user_role} not permitted for this endpoint",
            )
        # PRD §2.1: Therapist is entity-backed; X-User-ID must equal an existing
        # Therapist.id. Other roles are opaque and not validated against any row.
        if g.user_role == "Therapist":
            if g.user_id not in db.therapists:
                raise APIError(
                    ERR_FORBIDDEN,
                    403,
                    "X-User-ID does not name an existing Therapist",
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
        raise APIError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body
