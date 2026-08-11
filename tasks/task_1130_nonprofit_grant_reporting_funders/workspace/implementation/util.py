"""Shared helpers: ids, datetime parsing/formatting, decimal math, payload validation."""

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err_validation

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


def parse_datetime(value, field="date"):
    """Accept ISO 8601 date or datetime strings; normalize to aware UTC."""
    if not isinstance(value, str):
        raise err_validation("%s must be an ISO 8601 string" % field)
    s = value.strip()
    if _DATE_ONLY.match(s):
        s = s + "T00:00:00Z"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise err_validation("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Domain datetimes: seconds precision, milliseconds only when non-zero."""
    if dt is None:
        return None
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += ".%03d" % (dt.microsecond // 1000)
    return base + "Z"


def fmt_ts(dt):
    """created_at / updated_at / meta timestamps: always 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


# ---------- decimal helpers ----------

def to_dec(x):
    return Decimal(str(x))


def round_half_up_int(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(dec):
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def variance_pct(actual, budget):
    """round((actual - budget) / budget * 100, 2) half-up; budget == 0 => null."""
    if not budget:
        return None
    return round_half_up_2((Decimal(actual) - Decimal(budget)) / Decimal(budget) * Decimal(100))


# ---------- payload field helpers ----------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def get_str(data, field, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default
    if not isinstance(v, str):
        raise err_validation("%s must be a string" % field)
    return v


def get_nonempty_str(data, field, required=True, default=None):
    v = get_str(data, field, required=required, default=default)
    if v is not None and v == "":
        raise err_validation("%s must be non-empty" % field)
    return v


def get_enum(data, field, allowed, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("%s must be one of %s" % (field, ", ".join(allowed)))
    return v


def get_int(data, field, required=True, default=None, min_v=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default
    if not is_int(v):
        raise err_validation("%s must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err_validation("%s must be >= %s" % (field, min_v))
    return v


def get_num(data, field, required=True, default=None, min_v=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default
    if not is_num(v):
        raise err_validation("%s must be a number" % field)
    if min_v is not None and v < min_v:
        raise err_validation("%s must be >= %s" % (field, min_v))
    return v


def get_bool(data, field, required=False, default=False):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default
    if not isinstance(v, bool):
        raise err_validation("%s must be a boolean" % field)
    return v


def get_dt(data, field, required=True, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default
    return parse_datetime(v, field)


def get_arr(data, field, required=False, default=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_validation("Missing required field: %s" % field)
        return default if default is not None else []
    if not isinstance(v, list):
        raise err_validation("%s must be an array" % field)
    return v
