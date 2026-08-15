"""Auth header extraction, role checking, ownership helpers, pagination."""
from flask import request

from db import STORE
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

ROLES = {"ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact", "HaulerAdmin"}


def auth():
    """Priority 1: X-User-ID and X-User-Role present; role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(role, allowed):
    """Priority 3: caller role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403, "Caller role is not authorized for this endpoint")


def forbid_unless(condition):
    """Priority 4: ownership rejection for entity-backed roles."""
    if not condition:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "Caller does not own the referenced resource")


def get_or_404(bucket, rid):
    obj = STORE[bucket].get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Resource not found: {rid}")
    return obj


def paginate(items):
    """limit/offset parsing (defaults 10/0, limit min 1 max 100) + page meta."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def by_creation(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def filter_enum(args, name, allowed):
    val = args.get(name)
    if val is not None and val not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Invalid value for filter '{name}'")
    return val
