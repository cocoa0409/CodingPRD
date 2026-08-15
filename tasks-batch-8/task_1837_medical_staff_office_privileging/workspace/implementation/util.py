"""Datetime, body, and pagination helpers."""
import math
from datetime import datetime, timedelta, timezone

from flask import request

import errors


# --- Datetimes --------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Canonical ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_years(dt, years):
    """Calendar arithmetic in UTC (Feb 29 clamps to Feb 28)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def add_days(dt, days):
    return dt + timedelta(days=days)


def ceil_half_count(n):
    return max(3, math.ceil(n * 0.5))


# --- Request body -----------------------------------------------------------

def get_body():
    """Return the JSON request body as a dict; {} when absent."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        errors.raise_err(
            errors.ERR_INVALID_REQUEST,
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return v


def parse_dt_field(value, field):
    try:
        return parse_dt(value)
    except (ValueError, TypeError):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be ISO-8601 datetime")


def check_dt_order(start_raw, end_raw, start_name, end_name):
    s = parse_dt_field(start_raw, start_name)
    e = parse_dt_field(end_raw, end_name)
    if not s < e:
        errors.raise_err(
            errors.ERR_INVALID_REQUEST,
            f"{start_name} must be strictly earlier than {end_name}",
        )
    return s, e


# --- Pagination -------------------------------------------------------------

def pagination_params():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, serializer, filters):
    """Filter by exact-match query params, sort by created_at asc, paginate."""
    rows = list(records)
    for field in filters:
        raw = request.args.get(field)
        if raw is not None:
            rows = [r for r in rows if str(r.get(field)) == raw]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
    total = len(rows)
    limit, offset = pagination_params()
    page = rows[offset:offset + limit]
    return [serializer(r) for r in page], limit, offset, total
