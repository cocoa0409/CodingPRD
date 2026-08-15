"""Request-body validation helpers, datetime/date handling, pagination.

Shape failures raise ERR_INVALID_REQUEST (400). Specific bounded fields
(yield_pct) are validated by their route modules with their own error ids.
"""
import re
from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    """Decode the JSON request body. Missing body -> {}; wrong shape -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _bad(name):
    raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid field: %s" % name)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        _bad(name)
    return v


def opt_str(b, name, default=""):
    if name not in b:
        return default
    v = b[name]
    if not isinstance(v, str):
        _bad(name)
    return v


def req_int(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name)
    return v


def opt_int(b, name, default=0):
    if name not in b:
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name)
    return v


def _to_decimal(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return d


def req_num(b, name):
    d = _to_decimal(b.get(name))
    if d is None:
        _bad(name)
    return d


def opt_num(b, name, default=None):
    if name not in b:
        return default
    d = _to_decimal(b[name])
    if d is None:
        _bad(name)
    return d


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        _bad(name)
    return v


def opt_bool(b, name, default=False):
    if name not in b:
        return default
    v = b[name]
    if not isinstance(v, bool):
        _bad(name)
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        _bad(name)
    return v


def opt_enum(b, name, allowed, default):
    if name not in b:
        return default
    v = b[name]
    if not isinstance(v, str) or v not in allowed:
        _bad(name)
    return v


def parse_date_str(s):
    """'YYYY-MM-DD' -> date, else None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def req_date(b, name):
    """Required YYYY-MM-DD string; returns the raw string (parsed separately)."""
    v = b.get(name)
    if parse_date_str(v) is None:
        _bad(name)
    return v


def parse_instant(s):
    """ISO 8601 instant -> aware UTC datetime, else None. Naive read as UTC."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_instant(b, name):
    """Required ISO 8601 instant string; returns the raw string."""
    v = b.get(name)
    if parse_instant(v) is None:
        _bad(name)
    return v


def fmt(dt):
    """Canonical output format: ISO 8601 UTC with exactly 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def pagination():
    """limit/offset query params per PRD 2.3: limit default 10, 1..100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid offset")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def apply_filters(records, filter_names):
    """Exact-match query filters + created_at-ascending sort + pagination slice."""
    args = request.args
    items = [
        r for r in records
        if all(r.get(f) == args[f] for f in filter_names if f in args)
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = pagination()
    return items[offset:offset + limit], total, limit, offset
