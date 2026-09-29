"""Request-shape validation helpers (PRD §2.7 / §2.3)."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import err

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def q(value, places):
    """Round half up to `places` decimals; returns Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half up and return a JSON-friendly float."""
    return float(q(value, places))


def D(value):
    return Decimal(str(value))


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            if not re.fullmatch(r"[+-]?[0-9]+", limit_raw.strip()):
                raise ValueError
            limit = int(limit_raw.strip())
        except (ValueError, AttributeError):
            raise err("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            if not re.fullmatch(r"[+-]?[0-9]+", offset_raw.strip()):
                raise ValueError
            offset = int(offset_raw.strip())
        except (ValueError, AttributeError):
            raise err("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_PAGINATION", "offset must be non-negative")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


# --------------------------------------------------------------- scalars ---

def _fail(name, why):
    raise err("ERR_VALIDATION", "%s: %s" % (name, why))


def req_present(data, name):
    if name not in data or data[name] is None:
        _fail(name, "is required")
    return data[name]


def get_str(data, name, required=True, min_len=None, max_len=None, pattern=None, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return default
    v = data[name]
    if not isinstance(v, str):
        _fail(name, "must be a string")
    if min_len is not None and len(v) < min_len:
        _fail(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(v) > max_len:
        _fail(name, "must be at most %d characters" % max_len)
    if pattern is not None and not re.fullmatch(pattern, v):
        _fail(name, "does not match the required format")
    return v


def get_enum(data, name, members, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return default
    v = data[name]
    if not isinstance(v, str) or v not in members:
        _fail(name, "must be one of %s" % ", ".join(members))
    return v


def get_bool(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return default
    v = data[name]
    if not isinstance(v, bool):
        _fail(name, "must be a boolean")
    return v


def get_int(data, name, required=True, minimum=None, maximum=None, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(name, "must be an integer")
    if minimum is not None and v < minimum:
        _fail(name, "must be >= %s" % minimum)
    if maximum is not None and v > maximum:
        _fail(name, "must be <= %s" % maximum)
    return v


def get_num(data, name, required=True, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None, default=None, places=None):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(name, "must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        _fail(name, "must be a number")
    if minimum is not None and d < Decimal(str(minimum)):
        _fail(name, "must be >= %s" % minimum)
    if maximum is not None and d > Decimal(str(maximum)):
        _fail(name, "must be <= %s" % maximum)
    if exclusive_min is not None and d <= Decimal(str(exclusive_min)):
        _fail(name, "must be > %s" % exclusive_min)
    if exclusive_max is not None and d >= Decimal(str(exclusive_max)):
        _fail(name, "must be < %s" % exclusive_max)
    if places is not None:
        return float(q(d, places))
    return float(d)


def get_dt(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return default
    v = data[name]
    if not isinstance(v, str):
        _fail(name, "must be an ISO 8601 datetime string")
    return parse_dt(v, name)


def parse_dt(v, name="datetime"):
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _fail(name, "is not a parseable ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_list(data, name, min_items, max_items, required=True):
    if name not in data or data[name] is None:
        if required:
            _fail(name, "is required")
        return None
    v = data[name]
    if not isinstance(v, list):
        _fail(name, "must be an array")
    if len(v) < min_items or len(v) > max_items:
        _fail(name, "must contain between %d and %d entries" % (min_items, max_items))
    return v


def reject_unexpected_version(data):
    """PRD §2.5: outside the seven declared operations no endpoint takes a version field."""
    for f in ("expected_order_version", "expected_machine_version", "expected_purchase_order_version"):
        if f in data:
            _fail(f, "is not accepted by this endpoint")


def get_version(data, name):
    """Required, non-optional OCC input: omission is ERR_VALIDATION."""
    if name not in data or data[name] is None:
        _fail(name, "is required")
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(name, "must be an integer")
    return v


def iso(dt):
    """Render a datetime in the system's ISO 8601 UTC / 3-fractional-digit form."""
    import clock
    return clock.fmt(dt)
