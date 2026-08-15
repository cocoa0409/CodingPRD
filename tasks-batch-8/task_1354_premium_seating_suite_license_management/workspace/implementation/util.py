"""Shared utilities: timestamps, decimals, pagination, body validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


# ---------------------------------------------------------------- time
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 instant; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise errors.err_invalid_request(f"{field} must be an ISO8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err_invalid_request(f"{field} is not a valid ISO8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(start, end):
    """Whole days from start to end (floor); negative clamps handled by callers."""
    return int((end - start).total_seconds() // 86400)


# ---------------------------------------------------------------- decimal
def rhu(value):
    """Round a Decimal half-up to whole cents, returning int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x):
    """Exact Decimal from an int/float/str JSON value."""
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


# ---------------------------------------------------------------- body
def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def req_present(data, name):
    if name not in data or data[name] is None:
        raise errors.err_invalid_request(f"missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req_present(data, name)
    if not isinstance(v, str) or v == "":
        raise errors.err_invalid_request(f"{name} must be a non-empty string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, name, minimum=None, maximum=None):
    v = req_present(data, name)
    if not _is_int(v):
        raise errors.err_invalid_request(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"{name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.err_invalid_request(f"{name} must be <= {maximum}")
    return v


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not _is_int(v):
        raise errors.err_invalid_request(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"{name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.err_invalid_request(f"{name} must be <= {maximum}")
    return v


def req_enum(data, name, domain):
    v = req_present(data, name)
    if v not in domain:
        raise errors.err_invalid_request(f"{name} must be one of {sorted(domain)}")
    return v


def req_dt(data, name):
    return parse_dt(req_present(data, name), field=name)


# ---------------------------------------------------------------- pagination
def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, serializer=None):
    """Sort by created_at ASC then insertion sequence, then paginate."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    if serializer:
        page = [serializer(e) for e in page]
    return page, meta
