"""Auth, RBAC, pagination, and OCC helpers."""

from __future__ import annotations

from flask import request

from errors import (
    ERR_AUTH_REQUIRED,
    ERR_FORBIDDEN,
    ERR_PAGINATION_INVALID,
    ERR_VERSION_CONFLICT,
    raise_err,
)


VALID_ROLES = {"Streamer", "OperationsReviewer", "ComplianceReviewer", "PlatformAdmin"}


def require_auth() -> tuple[str, str]:
    """Read X-User-ID + X-User-Role headers; reject if absent or unknown role.

    Returns (user_id, role) on success.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_AUTH_REQUIRED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise_err(ERR_FORBIDDEN, f"Unknown role: {role}")
    return user_id, role


def require_role(role: str, allowed: list[str]) -> None:
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"Role {role} not permitted for this endpoint")


def parse_pagination():
    """Parse `limit`/`offset` query params; enforce min/max from PRD §2.3."""
    try:
        limit_raw = request.args.get("limit", "10")
        offset_raw = request.args.get("offset", "0")
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise_err(ERR_PAGINATION_INVALID, "Pagination params must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_PAGINATION_INVALID, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_PAGINATION_INVALID, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    window = items[offset: offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, pagination


def occ_check(entity: dict, body: dict | None) -> None:
    """If body has 'version', compare against entity['version']; else skip."""
    if not body or "version" not in body or body["version"] is None:
        return
    requested = body.get("version")
    current = entity.get("version")
    if requested != current:
        raise_err(ERR_VERSION_CONFLICT,
                  f"Version mismatch: provided={requested}, current={current}")
