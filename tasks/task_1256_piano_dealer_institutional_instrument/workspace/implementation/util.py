import uuid
from calendar import monthrange
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import invalid, not_found

MISSING = object()


def D(x):
    """Decimal from a JSON number without float artifacts."""
    return Decimal(str(x))


def rhu(x):
    """Round half-up to integer cents."""
    return int(D(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def parse_dt(value, field):
    if not isinstance(value, str):
        raise invalid('%s must be an ISO 8601 datetime string' % field)
    s = value.strip()
    try:
        if s.endswith(('Z', 'z')):
            dt = datetime.fromisoformat(s[:-1] + '+00:00')
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid('%s is not a valid ISO 8601 datetime' % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-month arithmetic: same day-of-month, clamped to month length."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def whole_months_between(start, end):
    """Calendar months elapsed; a month counts only once its day-of-month is reached."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid('request body must be a JSON object')
    return data


def require(data, name):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        raise invalid('missing required field: %s' % name)
    return v


def optional(data, name, default=None):
    v = data.get(name, MISSING)
    if v is MISSING or v is None:
        return default
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid('%s must be an integer' % name)
    if isinstance(v, float) and not v.is_integer():
        raise invalid('%s must be an integer' % name)
    return int(v)


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid('%s must be a number' % name)
    return v


def as_str(v, name):
    if not isinstance(v, str):
        raise invalid('%s must be a string' % name)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise invalid('%s must be a boolean' % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise invalid('%s must be one of %s' % (name, sorted(allowed)))
    return v


def as_list(v, name):
    if not isinstance(v, list):
        raise invalid('%s must be an array' % name)
    return v


def find(store, rid, what='resource'):
    rec = store.get(rid)
    if rec is None:
        raise not_found(what)
    return rec


def serialize(res, dt_fields=()):
    """Copy a stored resource for output: strip internal '_' keys, format datetimes."""
    out = {}
    for k, v in res.items():
        if k.startswith('_'):
            continue
        if k in dt_fields and v is not None:
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out
