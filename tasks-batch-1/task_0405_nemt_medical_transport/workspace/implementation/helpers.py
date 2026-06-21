"""Shared helpers: enum ranks, datetime parsing, validation primitives, rounding."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err

# Ordered enumerations (PRD 2.7)
MODALITY_ORDER = ["AMBULATORY", "WHEELCHAIR", "STRETCHER"]
LOS_ORDER = ["ROUTINE", "URGENT", "BARIATRIC"]


def modality_rank(m):
    return MODALITY_ORDER.index(m)


def los_rank(l):
    return LOS_ORDER.index(l)


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer (whole cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns timezone-aware UTC datetime or raises."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Expected an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_body_fields(body, *names):
    """Ensure all named fields are present (not None) in the body."""
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_enum(body, field, allowed):
    """Validate a present enum field's value is within the allowed set."""
    val = body.get(field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_number(body, field, allow_negative=False):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    if not allow_negative and val < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= 0" % field)
    return val


def require_int(body, field, allow_negative=False):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if not allow_negative and val < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= 0" % field)
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def get_json_body():
    """Return the JSON body as a dict; tolerate empty bodies."""
    from flask import request
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def parse_pagination():
    """Return (limit, offset) from query string per PRD 2.3.

    limit default 10, min 1, max 100; offset default 0. Out-of-domain values
    are rejected with ERR_INVALID_REQUEST.
    """
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list and return (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
