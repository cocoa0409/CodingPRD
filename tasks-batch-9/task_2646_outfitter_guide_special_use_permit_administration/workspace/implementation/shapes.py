"""Request-shape validation helpers (priority 5 -- ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_dt

E = "ERR_INVALID_REQUEST"


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(E, "request body must be a JSON object")
    return data


def bad(field, why):
    raise ApiError(E, "%s %s" % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, allowed=None, allow_empty=False):
    if not present(data, field):
        bad(field, "is required")
    val = data[field]
    if not isinstance(val, str):
        bad(field, "must be a string")
    if not allow_empty and not val.strip():
        bad(field, "must not be empty")
    if allowed is not None and val not in allowed:
        bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return val


def opt_str(data, field, allowed=None, default=None, allow_empty=True):
    if not present(data, field):
        return default
    val = data[field]
    if not isinstance(val, str):
        bad(field, "must be a string")
    if not allow_empty and not val.strip():
        bad(field, "must not be empty")
    if allowed is not None and val not in allowed:
        bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return val


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad(field, "is required")
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(val, field, minimum, maximum):
    if isinstance(val, bool):
        bad(field, "must be an integer")
    if isinstance(val, int):
        num = val
    elif isinstance(val, float):
        if val != int(val):
            bad(field, "must be an integer")
        num = int(val)
    elif isinstance(val, str):
        text = val.strip()
        neg = text.startswith("-")
        digits = text[1:] if neg or text.startswith("+") else text
        if not digits.isdigit():
            bad(field, "must be an integer")
        num = int(text)
    else:
        bad(field, "must be an integer")
    if minimum is not None and num < minimum:
        bad(field, "must be >= %s" % minimum)
    if maximum is not None and num > maximum:
        bad(field, "must be <= %s" % maximum)
    return num


def req_bool(data, field):
    if not present(data, field):
        bad(field, "is required")
    return _as_bool(data[field], field)


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    return _as_bool(data[field], field)


def _as_bool(val, field):
    if isinstance(val, bool):
        return val
    if isinstance(val, str) and val.lower() in ("true", "false"):
        return val.lower() == "true"
    bad(field, "must be a boolean")


def req_dec(data, field, minimum=None, maximum=None):
    if not present(data, field):
        bad(field, "is required")
    return _as_dec(data[field], field, minimum, maximum)


def opt_dec(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    return _as_dec(data[field], field, minimum, maximum)


def _as_dec(val, field, minimum, maximum):
    if isinstance(val, bool):
        bad(field, "must be a number")
    try:
        num = Decimal(str(val))
    except (InvalidOperation, ValueError):
        bad(field, "must be a number")
    if not num.is_finite():
        bad(field, "must be a finite number")
    if minimum is not None and num < Decimal(str(minimum)):
        bad(field, "must be >= %s" % minimum)
    if maximum is not None and num > Decimal(str(maximum)):
        bad(field, "must be <= %s" % maximum)
    return num


def req_date(data, field):
    if not present(data, field):
        bad(field, "is required")
    raw = data[field]
    if not isinstance(raw, str) or not raw.strip():
        bad(field, "must be an ISO-8601 date-time string")
    parse_dt(raw, E, field)
    return raw


def opt_date(data, field, default=None):
    if not present(data, field):
        return default
    raw = data[field]
    if not isinstance(raw, str) or not raw.strip():
        bad(field, "must be an ISO-8601 date-time string")
    parse_dt(raw, E, field)
    return raw


def req_id(data, field):
    return req_str(data, field)


def opt_id(data, field, default=None):
    val = data.get(field)
    if val is None:
        return default
    if not isinstance(val, str) or not val.strip():
        bad(field, "must be an id string")
    return val
