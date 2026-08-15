"""Datetime handling, numeric rounding, request body and field validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import bad_request


# ---------------------------------------------------------------------------
# Datetimes: ISO 8601 UTC with three fractional digits (PRD section 2.5).
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        raise bad_request("Expected an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise bad_request(f"Invalid ISO 8601 datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def trunc_second(dt):
    """Visit-frequency comparisons operate at second precision (PRD 2.9)."""
    return dt.replace(microsecond=0)


def month_key(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


def next_month(mk):
    y, m = int(mk[:4]), int(mk[5:7])
    m += 1
    if m > 12:
        y += 1
        m = 1
    return f"{y:04d}-{m:02d}"


# ---------------------------------------------------------------------------
# Rounding (PRD section 2.9: round half up; never float money math).
# ---------------------------------------------------------------------------

def round_half_up_int(d):
    return int(Decimal(d).to_integral_value(rounding=ROUND_HALF_UP))


def quantize(d, places):
    return Decimal(d).quantize(Decimal(places), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Request body and field validators. All failures are ERR_INVALID_REQUEST.
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data()
        if raw and raw.strip():
            raise bad_request("Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def _missing(name):
    raise bad_request(f"Missing required field: {name}")


def _bad(name, why):
    raise bad_request(f"Invalid field '{name}': {why}")


def v_str(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    if not isinstance(data[name], str):
        _bad(name, "must be a string")
    return data[name]


def v_int(data, name, required=True, default=None, lo=None, hi=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "must be an integer")
    if lo is not None and v < lo:
        _bad(name, f"must be >= {lo}")
    if hi is not None and v > hi:
        _bad(name, f"must be <= {hi}")
    return v


def v_bool(data, name, required=False, default=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    if not isinstance(data[name], bool):
        _bad(name, "must be a boolean")
    return data[name]


def v_enum(data, name, values, required=True, default=None):
    v = v_str(data, name, required=required, default=default)
    if v is None:
        return None
    if v not in values:
        _bad(name, "must be one of " + ", ".join(sorted(values)))
    return v


def v_dt(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    try:
        return parse_dt(data[name])
    except Exception as exc:
        if hasattr(exc, "error_id"):
            raise
        _bad(name, "must be an ISO 8601 datetime")


def v_num(data, name, required=True, default=None, gt=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "must be a number")
    d = Decimal(str(v))
    if gt is not None and not d > gt:
        _bad(name, f"must be > {gt}")
    return d


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3: limit default 10, min 1, max 100; offset 0).
# ---------------------------------------------------------------------------

def page_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if not 1 <= limit <= 100:
            _bad("limit", "must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Default list order: creation timestamp ascending (PRD 2.3)."""
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


def opt_enum_filter(name, values):
    """Validate an optional enum-valued query filter."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        _bad(name, "must be one of " + ", ".join(sorted(values)))
    return raw
