"""Shared validation/parse/pagination utilities."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err
from db import db

# Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def round_half_up(value):
    """Round a numeric/Decimal to the nearest whole integer, half rounding up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_apply_round(cents, bps):
    """cents * bps / 10000, round-half-up to whole cents (PRD §2.8)."""
    return round_half_up(Decimal(cents) * Decimal(bps) / Decimal(10000))


def parse_datetime(value, field="datetime"):
    """Parse an ISO 8601 datetime into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def as_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be <= {maximum}")
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", f"{field} must be a non-empty string")
    return val


def as_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return val


def as_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in choices:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(choices)}")
    return val


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def parse_pagination():
    """Read & validate limit/offset query params (PRD §2.3)."""
    from flask import request

    def _read(name, default, lo, hi):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            val = int(raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", f"{name} must be an integer")
        if val < lo or (hi is not None and val > hi):
            raise err("ERR_PAGINATION_INVALID", f"{name} out of allowed range")
        return val

    limit = _read("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _read("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC, slice, and produce pagination meta (PRD §2.3)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def lookup(collection, _id, name="resource"):
    """Existence check returning ERR_NOT_FOUND when absent (PRD §2.6)."""
    ent = collection.get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", f"{name} not found")
    return ent
