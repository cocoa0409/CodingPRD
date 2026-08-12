"""Request schema validation (validation priority layer 2: ERR_INVALID_REQUEST)
and pagination parameter handling (PRD section 2.3)."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

MISSING = object()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def get_body():
    raw = request.get_data(as_text=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal)
    except Exception:
        bad("Request body must be valid JSON")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def is_num(v):
    return isinstance(v, (int, Decimal)) and not isinstance(v, bool)


def field(data, name):
    v = data.get(name, MISSING)
    if v is MISSING:
        bad(f"Missing required field: {name}")
    return v


def req_str(data, name):
    v = field(data, name)
    if not isinstance(v, str):
        bad(f"Field {name} must be a string")
    return v


def opt_str_nullable(data, name, default=None):
    if name not in data:
        return default
    v = data[name]
    if v is not None and not isinstance(v, str):
        bad(f"Field {name} must be a string or null")
    return v


def req_int(data, name, gt=None):
    v = field(data, name)
    if isinstance(v, bool):
        bad(f"Field {name} must be an integer")
    if isinstance(v, Decimal):
        if v != v.to_integral_value():
            bad(f"Field {name} must be an integer")
        v = int(v)
    if not isinstance(v, int):
        bad(f"Field {name} must be an integer")
    if gt is not None and not v > gt:
        bad(f"Field {name} must be greater than {gt}")
    return v


def req_num(data, name, gt=None, ge=None, lt=None):
    v = field(data, name)
    if not is_num(v):
        bad(f"Field {name} must be a number")
    v = Decimal(v) if isinstance(v, int) else v
    if gt is not None and not v > gt:
        bad(f"Field {name} must be greater than {gt}")
    if ge is not None and not v >= ge:
        bad(f"Field {name} must be at least {ge}")
    if lt is not None and not v < lt:
        bad(f"Field {name} must be less than {lt}")
    return v


def req_tons(data, name):
    """A positive tonnage carried to three decimal places."""
    return req_num(data, name, gt=Decimal("0")).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP)


def opt_bool(data, name, default=False):
    if name not in data:
        return default
    v = data[name]
    if not isinstance(v, bool):
        bad(f"Field {name} must be a boolean")
    return v


def req_enum(data, name, allowed):
    v = field(data, name)
    if not isinstance(v, str) or v not in allowed:
        bad(f"Field {name} must be one of {sorted(allowed)}")
    return v


def parse_datetime(v, name):
    if not isinstance(v, str):
        bad(f"Field {name} must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        bad(f"Field {name} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(data, name):
    return parse_datetime(field(data, name), name)


def opt_dt(data, name):
    if name not in data or data[name] is None:
        return None
    return parse_datetime(data[name], name)


def req_date(data, name):
    v = field(data, name)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        bad(f"Field {name} must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        bad(f"Field {name} must be a valid YYYY-MM-DD date")


def pagination():
    """limit defaults to 10 (min 1, clamped to max 100); offset defaults to 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items):
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
