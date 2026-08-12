"""Shared utilities: ids, timestamps, decimals, pagination, validation helpers."""

import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err, ERR_VALIDATION


# ---------- ids & clock ----------

def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical-clock timestamp, ISO8601 UTC with 3 fractional digits."""
    dt = parse_dt(db.clock_iso)
    return fmt_dt(dt)


def fmt_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse ISO8601 datetime. Accepts trailing Z or offset."""
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date string")
    return date.fromisoformat(s.strip())


def clock_dt():
    return parse_dt(db.clock_iso)


def clock_date():
    return clock_dt().date()


# ---------- decimals ----------

TWO_PLACES = Decimal("0.01")


def d(x):
    """Coerce to Decimal from int/float/str without binary float artifacts."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise ValueError(f"cannot convert {type(x)} to Decimal")


def round2(x):
    return d(x).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def num_out(x):
    """Serialize a Decimal as a JSON number. Integers emit as int; 2dp emit as float.

    The PRD treats gallon/brix numbers as decimal; we emit float(x) which for values
    quantized to 2dp renders the shortest exact representation (e.g. 1.5, 12.34).
    """
    if isinstance(x, Decimal):
        f = float(x)
        return f
    return x


# ---------- pagination ----------

def parse_pagination(args):
    """Read limit/offset from query args per PRD §2.3. Defaults 10/0; limit 1..100."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------- field validation helpers ----------

def body_json():
    from flask import request
    if not request.is_json:
        raise_err(ERR_VALIDATION, "request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def check_unknown_fields(data, allowed):
    for k in data:
        if k not in allowed:
            raise_err(ERR_VALIDATION, f"unknown field: {k}")


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err(ERR_VALIDATION, f"missing required field: {f}")


def as_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_VALIDATION, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_VALIDATION, f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise_err(ERR_VALIDATION, f"{field} must be <= {maximum}")
    return value


def as_number(value, field, minimum=None, maximum=None, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_VALIDATION, f"{field} must be a number")
    v = d(value)
    if minimum is not None:
        if exclusive_min:
            if v <= d(minimum):
                raise_err(ERR_VALIDATION, f"{field} must be > {minimum}")
        else:
            if v < d(minimum):
                raise_err(ERR_VALIDATION, f"{field} must be >= {minimum}")
    if maximum is not None and v > d(maximum):
        raise_err(ERR_VALIDATION, f"{field} must be <= {maximum}")
    return v


def as_str(value, field):
    if not isinstance(value, str) or not value:
        raise_err(ERR_VALIDATION, f"{field} must be a non-empty string")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise_err(ERR_VALIDATION, f"{field} must be a boolean")
    return value


def as_enum(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        raise_err(ERR_VALIDATION, f"{field} must be one of {sorted(choices)}")
    return value
