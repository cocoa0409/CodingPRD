"""Auth header extraction, role checking, body/pagination helpers (PRD §2.1, §2.3, §2.5).

Validation precedence ladder (PRD §2.5 / scaffold §1.4):
  1. ERR_UNAUTHENTICATED (401) — X-User-ID and X-User-Role present, role recognised
  2. ERR_FORBIDDEN_ROLE (403) — acting role permitted for this operation
  3. ERR_NOT_FOUND (404) — path ids + body FKs resolve
  4. ERR_INVALID_REQUEST (422) — body schema
  5. ERR_INVALID_STATE (409) — transition defined from current state
  6+. operation-specific business rules
"""
from __future__ import annotations

from typing import Iterable, Optional
from flask import request, g

from errors import (
    APIError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_PAGINATION_INVALID,
)

# The five recognised roles (PRD §2.1).
ALLOWED_ROLES = {"Clerk", "Judge", "Mediator", "Petitioner", "Respondent"}


def _extract_headers() -> None:
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    if role not in ALLOWED_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, f"Unknown role: {role}")

    g.user_role = role
    g.user_id = user_id


def require_auth(allowed_roles: Iterable[str]):
    """Validate headers + restrict to the given roles.

    Returns a no-arg callable invoked at the top of each route handler so the
    auth (401) check fires strictly before the role (403) check.
    """
    allowed_set = set(allowed_roles)

    def _check():
        _extract_headers()
        if g.user_role not in allowed_set:
            raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def get_json_body() -> dict:
    """Return the parsed JSON body; missing body becomes an empty dict.

    Raises ERR_INVALID_REQUEST if the body is present but is not a JSON object.
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


def paginate_params(args) -> tuple:
    """Read pagination params (PRD §2.3). Defaults limit=10/offset=0, limit in
    [1,100], offset >= 0. Out-of-range -> ERR_PAGINATION_INVALID (422).
    """
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    limit = 10 if limit_raw is None else limit_raw
    offset = 0 if offset_raw is None else offset_raw
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise APIError(ERR_PAGINATION_INVALID, 422, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise APIError(ERR_PAGINATION_INVALID, 422, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_PAGINATION_INVALID, 422, "offset must be >= 0")
    return limit, offset


def slice_page(items: list, limit: int, offset: int) -> tuple:
    """Apply offset/limit slicing; returns (page_items, total_count)."""
    total = len(items)
    return items[offset: offset + limit], total
