"""Validation extractors, date/decimal helpers, pagination."""

import re
from datetime import datetime, date, timezone

from decimal import Decimal, ROUND_HALF_UP
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def D(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def round0(v):
    """Round half-up (half away from zero) to whole cents -> int."""
    return int(D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(v):
    """Round half-up to 2 decimal places -> Decimal."""
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num_out(v):
    """Serialize a tonnage-style number at 2dp."""
    return float(round2(v))


def invalid(msg="invalid request"):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("request body must be a JSON object")
    return data


def req(data, name):
    if name not in data or data[name] is None:
        invalid(f"missing required field: {name}")
    return data[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        invalid(f"field {name} must be a non-empty string")
    return v


def as_number(v, name):
    """Accept JSON int/float (never bool) -> Decimal."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid(f"field {name} must be a number")
    return Decimal(str(v))


def as_int(v, name):
    if isinstance(v, bool):
        invalid(f"field {name} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    invalid(f"field {name} must be an integer")


def as_bool(v, name):
    if not isinstance(v, bool):
        invalid(f"field {name} must be a boolean")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        invalid(f"field {name} must be one of {sorted(allowed)}")
    return v


def parse_date(v):
    """Accept YYYY-MM-DD or a full ISO datetime; return a date or None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if DATE_RE.match(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def as_date(v, name):
    d = parse_date(v)
    if d is None:
        invalid(f"field {name} must be a date (YYYY-MM-DD)")
    return d


def parse_datetime(v):
    """Parse an ISO 8601 instant (Z or offset); date-only treated as midnight UTC."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    try:
        if DATE_RE.match(s):
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def date_str(d):
    """Normalize a date back to YYYY-MM-DD for output."""
    return d.isoformat() if isinstance(d, date) else d


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0, min 0. Values out
    of range are clamped; non-integer values are a schema error."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Items must already be sorted (created_at ascending). Returns
    (page, pagination-meta-dict)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
