"""Decimal / timestamp / payload-validation helpers."""

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import invalid

ZERO = Decimal("0")


def D(v):
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def q(v, places):
    exp = Decimal(1).scaleb(-places)
    return D(v).quantize(exp, rounding=ROUND_HALF_UP)


def q0(v):
    return q(v, 0)


def q2(v):
    return q(v, 2)


def q3(v):
    return q(v, 3)


def q4(v):
    return q(v, 4)


def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def num(v):
    """Serialise a Decimal to a JSON number."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        if v == v.to_integral_value() and -1e15 < v < 1e15:
            # keep the declared scale (e.g. 1234.00 -> 1234.0) as a float
            return float(v)
        return float(v)
    return v


def parse_iso(value, field):
    if not isinstance(value, str) or not value.strip():
        invalid("%s must be an ISO 8601 timestamp" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        invalid("%s must be an ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("request body must be a JSON object")
    return data


def present(payload, field):
    return field in payload and payload[field] is not None


def require(payload, fields):
    for field in fields:
        if field not in payload or payload[field] is None:
            invalid("%s is required" % field)
        value = payload[field]
        if isinstance(value, str) and not value.strip():
            invalid("%s is required" % field)


def enum(payload, field, allowed, required=True):
    if not present(payload, field):
        if required:
            invalid("%s is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        invalid("%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return value


def number(payload, field, minv=None, maxv=None, gt=None, lt=None,
           required=True, integer=False):
    if not present(payload, field):
        if required:
            invalid("%s is required" % field)
        return None
    value = payload[field]
    if isinstance(value, bool):
        invalid("%s must be a number" % field)
    if integer:
        if not isinstance(value, int):
            invalid("%s must be an integer" % field)
        dec = Decimal(value)
    else:
        if not isinstance(value, (int, float)):
            invalid("%s must be a number" % field)
        try:
            dec = D(value)
        except InvalidOperation:
            invalid("%s must be a number" % field)
        if not dec.is_finite():
            invalid("%s must be a finite number" % field)
    if minv is not None and dec < D(minv):
        invalid("%s must be >= %s" % (field, minv))
    if maxv is not None and dec > D(maxv):
        invalid("%s must be <= %s" % (field, maxv))
    if gt is not None and dec <= D(gt):
        invalid("%s must be > %s" % (field, gt))
    if lt is not None and dec >= D(lt):
        invalid("%s must be < %s" % (field, lt))
    if integer:
        return int(value)
    return dec


def text(payload, field, minlen=1, maxlen=None, required=True):
    if not present(payload, field):
        if required:
            invalid("%s is required" % field)
        return None
    value = payload[field]
    if not isinstance(value, str):
        invalid("%s must be a string" % field)
    stripped = value.strip()
    if minlen is not None and len(stripped) < minlen:
        invalid("%s must be at least %d characters" % (field, minlen))
    if maxlen is not None and len(stripped) > maxlen:
        invalid("%s must be at most %d characters" % (field, maxlen))
    return stripped


def state_code(payload, field="state_code", required=True):
    value = text(payload, field, minlen=1, maxlen=None, required=required)
    if value is None:
        return None
    if not re.match(r"^[A-Z]{2}$", value):
        invalid("%s must be exactly two uppercase letters" % field)
    return value


def boolean(payload, field, default=None, required=False):
    if not present(payload, field):
        if required:
            invalid("%s is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        invalid("%s must be a boolean" % field)
    return value


def window(payload, start_field, end_field):
    start = parse_iso(payload.get(start_field), start_field)
    end = parse_iso(payload.get(end_field), end_field)
    if not start < end:
        invalid("%s must be strictly earlier than %s" % (start_field, end_field))
    return start, end


def paging():
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def filter_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None
