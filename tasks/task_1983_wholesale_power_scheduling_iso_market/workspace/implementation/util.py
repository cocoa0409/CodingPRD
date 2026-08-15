"""Shared helpers: timestamps, decimals, ids, serialization, body validation."""
import math
import string
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import store
from errors import invalid_request

getcontext().prec = 40

_ALNUM = string.ascii_letters + string.digits


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


# ---------------------------------------------------------------- timestamps
def now_ts():
    """Wall-clock UTC timestamp with three fractional digits; monotonic so
    updated_at strictly increases across rapid successive mutations."""
    t = datetime.now(timezone.utc)
    if store.last_ts is not None and t <= store.last_ts:
        t = store.last_ts + timedelta(milliseconds=1)
    store.last_ts = t
    ms = t.microsecond // 1000
    return t.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def fmt_dt(dt):
    """Format a datetime as ISO-8601 UTC (seconds precision when whole)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_datetime(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        parts = value.split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            return None
        return datetime(int(parts[0]), int(parts[1]), int(parts[2]), tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_month(value):
    if not isinstance(value, str):
        return None
    try:
        parts = value.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            return None
        y, m = int(parts[0]), int(parts[1])
        if m < 1 or m > 12:
            return None
        return "%04d-%02d" % (y, m)
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ decimals
def to_decimal(value):
    """Convert an incoming JSON number to an exact Decimal (via str)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return Decimal(str(value))
    return None


def rhu(value):
    """Round half up to whole cents -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Serialize a Decimal/int as int when integral, else float."""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def touch(record):
    record["version"] += 1
    record["updated_at"] = now_ts()


def new_record():
    ts = now_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": store.next_seq()}


# ---------------------------------------------------------------- validation
def get_body():
    """Return the request JSON body as a dict, or raise ERR_INVALID_REQUEST."""
    from flask import request
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise invalid_request("request body must be a JSON object")
    return data


def check_unknown(body, allowed):
    for key in body:
        if key not in allowed:
            raise invalid_request("unknown field: %s" % key)


def req_string(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        raise invalid_request("field %s is required and must be a string" % field)
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request("field %s must be a string" % field)
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("field %s is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise invalid_request("field %s is below minimum" % field)
    if maximum is not None and v > maximum:
        raise invalid_request("field %s is above maximum" % field)
    return v


def opt_int(body, field, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return None
    return req_int(body, field, minimum, maximum)


def req_number(body, field, minimum=None, min_exclusive=False):
    v = to_decimal(body.get(field))
    if v is None:
        raise invalid_request("field %s is required and must be a number" % field)
    if minimum is not None:
        if min_exclusive and v <= minimum:
            raise invalid_request("field %s must be greater than %s" % (field, minimum))
        if not min_exclusive and v < minimum:
            raise invalid_request("field %s must be at least %s" % (field, minimum))
    return v


def opt_number(body, field):
    if field not in body or body.get(field) is None:
        return None
    v = to_decimal(body.get(field))
    if v is None:
        raise invalid_request("field %s must be a number" % field)
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        raise invalid_request("field %s must be one of %s" % (field, sorted(values)))
    return v


def req_datetime(body, field):
    v = body.get(field)
    dt = parse_datetime(v)
    if dt is None:
        raise invalid_request("field %s must be an ISO-8601 datetime" % field)
    return v, dt


def opt_datetime(body, field):
    if field not in body or body.get(field) is None:
        return None, None
    return req_datetime(body, field)


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def serialize(rec):
    """Strip internal keys; Decimal -> number; datetime -> ISO string."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = num(v)
        elif isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out
