"""Request schema validation (PRD 2.7 step 4). Every failure here is
ERR_INVALID_REQUEST / 422."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from dec import scale_of
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        bad("request body must be valid JSON")
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def _present(data, name):
    if name not in data or data[name] is None:
        return False
    return True


def req_present(data, name):
    if name not in data:
        bad("%s is required" % name)
    if data[name] is None:
        bad("%s must not be null" % name)
    return data[name]


def string(data, name, required=True, max_len=None, pattern=None,
           allow_empty=False, default=None):
    if not _present(data, name):
        if required:
            req_present(data, name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if not allow_empty and value.strip() == "":
        bad("%s must be non-empty" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s exceeds maximum length %d" % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("%s has an invalid format" % name)
    return value


def enum(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            req_present(data, name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, sorted(allowed)))
    return value


def boolean(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            req_present(data, name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def integer(data, name, required=True, ge=None, le=None, gt=None,
            multiple_of=None, default=None):
    if not _present(data, name):
        if required:
            req_present(data, name)
        return default
    value = data[name]
    if isinstance(value, bool):
        bad("%s must be an integer" % name)
    if isinstance(value, int):
        result = value
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            bad("%s must be an integer" % name)
        result = int(value)
    else:
        bad("%s must be an integer" % name)
    if gt is not None and result <= gt:
        bad("%s must be greater than %s" % (name, gt))
    if ge is not None and result < ge:
        bad("%s must be at least %s" % (name, ge))
    if le is not None and result > le:
        bad("%s must be at most %s" % (name, le))
    if multiple_of is not None and result % multiple_of != 0:
        bad("%s must be a multiple of %d" % (name, multiple_of))
    return result


def number(data, name, scale, required=True, gt=None, ge=None, le=None,
           lt=None, default=None):
    """Fixed-scale decimal input. Scale over the declared precision is a
    schema violation (PRD 2.7 step 4)."""
    if not _present(data, name):
        if required:
            req_present(data, name)
        return default
    value = data[name]
    if isinstance(value, bool):
        bad("%s must be a number" % name)
    if isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, Decimal):
        result = value
    else:
        bad("%s must be a number" % name)
    try:
        if not result.is_finite():
            bad("%s must be a finite number" % name)
    except (InvalidOperation, AttributeError):
        bad("%s must be a number" % name)
    if scale_of(result) > scale:
        bad("%s must carry at most %d decimal places" % (name, scale))
    if gt is not None and result <= Decimal(str(gt)):
        bad("%s must be greater than %s" % (name, gt))
    if ge is not None and result < Decimal(str(ge)):
        bad("%s must be at least %s" % (name, ge))
    if lt is not None and result >= Decimal(str(lt)):
        bad("%s must be less than %s" % (name, lt))
    if le is not None and result > Decimal(str(le)):
        bad("%s must be at most %s" % (name, le))
    return result


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value, name):
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 UTC timestamp string" % name)
    text = value.strip()
    m = _DT_RE.match(text)
    if not m:
        bad("%s must be an ISO 8601 UTC timestamp" % name)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        bad("%s is not a valid timestamp" % name)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tzs = tz[1:].replace(":", "")
        offset_minutes = int(tzs[:2]) * 60 + int(tzs[2:4])
        from datetime import timedelta
        dt = dt - sign * timedelta(minutes=offset_minutes)
    return dt


def timestamp(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            req_present(data, name)
        return default
    return parse_datetime(data[name], name)


def query_bool(args, name):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    low = str(raw).strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    return None
