"""Auth header extraction and RBAC (PRD §2.1, §2.11; scaffold §1.4 / §1.7).

Validation priority (PRD §2.11):
  1. ERR_UNAUTHENTICATED (401) — both X-User-ID and X-User-Role present AND
     X-User-Role is one of the four exact roles.
  2. ERR_UNAUTHORIZED (403)   — the recognised role is permitted for this op.
  (3. ERR_SEGREGATION_OF_DUTIES is checked inside the two clinical-closure routes,
      after auth/authorization but before existence — handled per-route.)

Roles (PRD §2.1):
  PlatformAdmin, ClaimsAdjuster, MedicalReviewer  -> opaque operator identities
  Employer                                        -> entity-backed (X-User-ID == Employer.id)
"""
from __future__ import annotations

from typing import Iterable, Optional
from flask import request, g

from errors import (
    APIError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_INVALID_REQUEST,
)

ALLOWED_ROLES = {"PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer", "Employer"}


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
    """Return a no-arg callable enforcing auth + role membership.

    Call it at the top of each route handler.
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(ERR_UNAUTHORIZED, 403, "Role not permitted for this operation")

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def get_json_body() -> dict:
    """Parse the JSON body; missing body -> empty dict.

    Raises ERR_INVALID_REQUEST if a present body is not a JSON object.
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
