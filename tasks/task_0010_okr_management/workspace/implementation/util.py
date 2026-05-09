"""Shared utilities: ID generation, common-fields helpers, decimal rounding, pagination."""

import uuid
from decimal import Decimal, ROUND_HALF_UP
from flask import g, request

from clock import now, format_ts
from errors import ApiError


def gen_id() -> str:
    return uuid.uuid4().hex


def round4(x) -> float:
    """Round half-up to 4 decimal places, return float."""
    if x is None:
        return None
    d = Decimal(str(x)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    # Normalize trailing zeros for JSON; but keep numeric
    return float(d)


def stamp_create(entity: dict, *, with_version=True) -> dict:
    ts = format_ts(now())
    entity["id"] = gen_id()
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def stamp_update(entity: dict):
    entity["updated_at"] = format_ts(now())
    entity["version"] = int(entity.get("version", 1)) + 1


def parse_pagination():
    """Extract limit/offset query params with defaults+bounds, raises ERR_INVALID_REQUEST."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "pagination params out of range")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def require_fields(body: dict, *names):
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "JSON body required")
    missing = [n for n in names if n not in body or body[n] is None]
    if missing:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required fields: {missing}")


def get_json_body():
    """Safe JSON body parse — returns {} if no body."""
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    return body or {}


def actor_id():
    return getattr(g, "actor_user_id", None)


def actor_role():
    return getattr(g, "actor_role", None)
