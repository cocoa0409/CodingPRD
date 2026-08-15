import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import request
from errors import ApiError


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def no_unknown(b, allowed):
    extra = [k for k in b.keys() if k not in allowed]
    if extra:
        _bad(f"Unknown request field: {extra[0]}")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return _is_int(v) or isinstance(v, float)


def req_str(b, name):
    if name not in b or b[name] is None:
        _bad(f"Missing required field: {name}")
    if not isinstance(b[name], str):
        _bad(f"Field {name} must be a string")
    return b[name]


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], str):
        _bad(f"Field {name} must be a string")
    return b[name]


def req_int(b, name, lo=None, hi=None):
    if name not in b or b[name] is None:
        _bad(f"Missing required field: {name}")
    v = b[name]
    if not _is_int(v):
        _bad(f"Field {name} must be an integer")
    if lo is not None and v < lo:
        _bad(f"Field {name} below minimum {lo}")
    if hi is not None and v > hi:
        _bad(f"Field {name} above maximum {hi}")
    return v


def opt_int(b, name, lo=None, hi=None, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not _is_int(v):
        _bad(f"Field {name} must be an integer")
    if lo is not None and v < lo:
        _bad(f"Field {name} below minimum {lo}")
    if hi is not None and v > hi:
        _bad(f"Field {name} above maximum {hi}")
    return v


def req_enum(b, name, values):
    v = req_str(b, name)
    if v not in values:
        _bad(f"Field {name} must be one of {sorted(values)}")
    return v


def req_pct(b, name, hi):
    """Allocation percentage: numeric, at most 2 decimal places, 0 < v <= hi.
    Returned as a Decimal quantized to 2dp."""
    if name not in b or b[name] is None:
        _bad(f"Missing required field: {name}")
    v = b[name]
    if not _is_num(v):
        _bad(f"Field {name} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        _bad(f"Field {name} must be a number")
    if d.is_nan() or d.is_infinite():
        _bad(f"Field {name} must be a finite number")
    q = d.quantize(Decimal("0.01"))
    if d != q:
        _bad(f"Field {name} must have at most two decimal places")
    if q <= 0 or q > hi:
        _bad(f"Field {name} out of range")
    return q


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_str(v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        _bad("Date must be YYYY-MM-DD")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        _bad("Invalid calendar date")


def req_date(b, name):
    if name not in b or b[name] is None:
        _bad(f"Missing required field: {name}")
    return parse_date_str(b[name])


def parse_datetime_val(v):
    """ISO 8601 UTC datetime; requires an explicit UTC offset (Z or +00:00-style)."""
    if not isinstance(v, str):
        _bad("Datetime must be an ISO 8601 string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad("Invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        _bad("Datetime must carry a UTC offset")
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    if name not in b or b[name] is None:
        _bad(f"Missing required field: {name}")
    return parse_datetime_val(b[name])


def req_list(b, name):
    if name not in b or b[name] is None:
        _bad(f"Missing required field: {name}")
    if not isinstance(b[name], list):
        _bad(f"Field {name} must be an array")
    return b[name]


def pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw, 10)
        except (ValueError, TypeError):
            _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit out of range [1, 100]")
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw, 10)
        except (ValueError, TypeError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset out of range")
    return limit, offset
