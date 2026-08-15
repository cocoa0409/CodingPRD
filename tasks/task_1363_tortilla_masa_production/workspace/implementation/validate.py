"""Request-body field validation helpers.

Phase order per PRD section 2.9:
  presence/type/basic shape -> ERR_INVALID_REQUEST (400)
  enum membership           -> ERR_INVALID_ENUM (400)
  semantic numeric ranges   -> ERR_VALIDATION (422)
"""
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation
from flask import request
from errors import err


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def need_str(b, f):
    v = b.get(f)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' is required and must be a non-empty string")
    return v


def opt_str(b, f):
    v = b.get(f)
    if v is None:
        return None
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' must be a string")
    return v


def need_num(b, f):
    v = b.get(f)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' is required and must be a number")
    return Decimal(str(v))


def opt_num(b, f):
    v = b.get(f)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' must be a number")
    return Decimal(str(v))


def need_int(b, f):
    v = b.get(f)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' is required and must be an integer")
    return v


def need_enum(b, f, allowed):
    v = b.get(f)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' is required and must be a string")
    if v not in allowed:
        err("ERR_INVALID_ENUM", 400, f"Field '{f}' must be one of {sorted(allowed)}")
    return v


def opt_enum(b, f, allowed):
    v = b.get(f)
    if v is None:
        return None
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field '{f}' must be a string")
    if v not in allowed:
        err("ERR_INVALID_ENUM", 400, f"Field '{f}' must be one of {sorted(allowed)}")
    return v


def parse_dt_value(v, field="value"):
    if not isinstance(v, str) or not v.strip():
        err("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO 8601 datetime string")
    t = v.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def need_dt(b, f):
    return parse_dt_value(b.get(f), f)


def parse_date_value(v, field="value"):
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO date string")
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO date string")


def need_date(b, f):
    return parse_date_value(b.get(f), f)


def parse_pagination():
    """limit default 10 (min 1, max 100), offset default 0. Out-of-range clamps."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, serializer):
    """items: full filtered list; sorts by creation order (created_at ASC)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(e) for e in page], limit, offset, total
