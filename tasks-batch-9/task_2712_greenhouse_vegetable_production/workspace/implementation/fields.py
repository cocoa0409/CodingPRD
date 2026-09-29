"""Field level presence / type / bound validation (rejection priority 4) and
enumeration membership (priority 5)."""
from datetime import date, datetime, timezone

from errors import ApiError
from money import D

MISSING = object()


def _fail(name, detail):
    raise ApiError("ERR_VALIDATION", "%s %s" % (name, detail))


def parse_datetime(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _present(payload, name, required):
    if name not in payload or payload[name] is None:
        if required:
            _fail(name, "is required")
        return MISSING
    return payload[name]


def string(payload, name, required=True, min_len=None, max_len=None, default=None):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    if not isinstance(raw, str):
        _fail(name, "must be a string")
    if min_len is not None and len(raw) < min_len:
        _fail(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(raw) > max_len:
        _fail(name, "must be at most %d characters" % max_len)
    return raw


def integer(payload, name, required=True, lo=None, hi=None, default=None):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    if isinstance(raw, bool):
        _fail(name, "must be an integer")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, float) and float(raw).is_integer():
        value = int(raw)
    else:
        _fail(name, "must be an integer")
    if lo is not None and value < lo:
        _fail(name, "must be at least %s" % lo)
    if hi is not None and value > hi:
        _fail(name, "must be at most %s" % hi)
    return value


def number(payload, name, required=True, lo=None, hi=None, default=None,
           exclusive_lo=False, exclusive_hi=False):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        _fail(name, "must be a number")
    value = D(raw)
    if lo is not None:
        bound = D(lo)
        if (value <= bound) if exclusive_lo else (value < bound):
            _fail(name, "must be greater than %s" % lo)
    if hi is not None:
        bound = D(hi)
        if (value >= bound) if exclusive_hi else (value > bound):
            _fail(name, "must be at most %s" % hi)
    return value


def boolean(payload, name, required=True, default=None):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    if not isinstance(raw, bool):
        _fail(name, "must be a boolean")
    return raw


def timestamp(payload, name, required=True, default=None):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    parsed = parse_datetime(raw)
    if parsed is None:
        _fail(name, "must be an ISO 8601 UTC timestamp")
    return parsed


def day(payload, name, required=True, default=None):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    parsed = parse_date(raw)
    if parsed is None:
        _fail(name, "must be a YYYY-MM-DD calendar date")
    return parsed


def enum_slot(payload, name, required=True, default=None):
    """Priority 4 half of an enum field: presence plus string type only."""
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    if not isinstance(raw, str):
        _fail(name, "must be a string")
    return raw


def enum_value(value, name, members, allow_none=True):
    """Priority 5 half of an enum field: membership."""
    if value is None and allow_none:
        return None
    if value not in members:
        raise ApiError(
            "ERR_INVALID_ENUM_VALUE",
            "%s must be one of %s" % (name, ", ".join(members)),
        )
    return value


def number_list(payload, name, required=True, lo=None, hi=None, default=None):
    raw = _present(payload, name, required)
    if raw is MISSING:
        return default
    if not isinstance(raw, list):
        _fail(name, "must be an array of numbers")
    out = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _fail(name, "must contain only numbers")
        value = D(item)
        if lo is not None and value < D(lo):
            _fail(name, "entries must be at least %s" % lo)
        if hi is not None and value > D(hi):
            _fail(name, "entries must be at most %s" % hi)
        out.append(value)
    return out


def reject_unless(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)
