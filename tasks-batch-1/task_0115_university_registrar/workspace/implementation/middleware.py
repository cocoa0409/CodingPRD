"""Auth header extraction, RBAC, and pagination parsing.

Auth headers (PRD §2.1):
  - X-User-ID:   acting principal id. For Student role it is the Student.id used
                 for ownership checks; for Advisor/Registrar/Bursar it is an
                 opaque operator id not tied to any entity.
  - X-User-Role: one of exactly Student | Advisor | Registrar | Bursar.
"""
from __future__ import annotations

from typing import Optional

from flask import g, request

from errors import err

KNOWN_ROLES = {"Student", "Advisor", "Registrar", "Bursar"}


def authenticate() -> None:
    """Validate auth headers; populate g.user_role / g.user_id.

    Priority 1 (PRD §3.11): missing or unknown role -> ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a known role")
    if not user_id:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID header missing")
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed: str) -> None:
    """Priority 2 (PRD §3.11): recognized but unpermitted role -> ERR_FORBIDDEN."""
    if g.user_role not in allowed:
        raise err("ERR_FORBIDDEN", "Acting role is not permitted for this operation")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


def parse_pagination() -> tuple[int, int]:
    """Parse limit/offset query params (PRD §2.3).

    Defaults: limit=10, offset=0. limit must be in [1,100]; offset >= 0.
    Out-of-range -> ERR_PAGINATION_INVALID (priority 2.7).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be zero or greater")

    return limit, offset
