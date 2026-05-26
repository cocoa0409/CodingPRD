"""Auth header extraction (PRD §2.1)."""
from __future__ import annotations

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"DistrictAdmin", "Guardian", "Anonymous"}


def get_auth(allow_anonymous_missing_id: bool = False):
    """Return (user_id, role).

    Both headers must be present and well-formed; role must be one of the three.
    For Anonymous on register endpoint, X-User-ID is optional.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-Role header")
    if role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"Unknown role {role!r}")
    if role == "Anonymous":
        # Anonymous role is acceptable without X-User-ID
        return user_id or "", role
    if not user_id:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID header")
    return user_id, role


def require_role(role: str, allowed: list):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"Role {role!r} not permitted for this operation")


def parse_pagination():
    """Read & validate ?limit&offset query params per PRD §2.3."""
    from errors import ERR_INVALID_REQUEST
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
