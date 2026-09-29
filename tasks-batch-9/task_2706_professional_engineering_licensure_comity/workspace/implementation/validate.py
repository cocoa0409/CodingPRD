"""Request-body and query-string validation (ladder rung 3)."""
import json
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import dec, decimal_places, parse_iso, parse_year_month

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        bad("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req_present(data, name):
    if not _present(data, name):
        bad("%s is required" % name)
    return data[name]


# --------------------------------------------------------------------- strings
def check_str(name, value, *, max_len=None, min_len=1):
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if min_len is not None and len(value.strip()) < min_len:
        bad("%s must be a non-empty string" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    return value


def req_str(data, name, *, max_len=None, min_len=1):
    return check_str(name, req_present(data, name), max_len=max_len, min_len=min_len)


def opt_str(data, name, *, max_len=None, min_len=1, default=None):
    if not _present(data, name):
        return default
    return check_str(name, data[name], max_len=max_len, min_len=min_len)


def req_state_code(data, name):
    value = req_str(data, name)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("%s must be exactly two uppercase letters" % name)
    return value


# ----------------------------------------------------------------------- enums
def check_enum(name, value, allowed):
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def req_enum(data, name, allowed):
    return check_enum(name, req_present(data, name), allowed)


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return check_enum(name, data[name], allowed)


# --------------------------------------------------------------------- numbers
def check_int(name, value, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s" % (name, maximum))
    return value


def req_int(data, name, *, minimum=None, maximum=None):
    return check_int(name, req_present(data, name), minimum=minimum, maximum=maximum)


def opt_int(data, name, *, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        return default
    return check_int(name, data[name], minimum=minimum, maximum=maximum)


def check_num(name, value, *, minimum=None, maximum=None, places=None,
              exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("%s must be a number" % name)
    try:
        number = dec(value)
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % name)
    if number != number:  # NaN
        bad("%s must be a number" % name)
    if places is not None and decimal_places(number) > places:
        bad("%s may carry at most %d decimal place(s)" % (name, places))
    if minimum is not None and number < dec(minimum):
        bad("%s must be at least %s" % (name, minimum))
    if exclusive_min is not None and number <= dec(exclusive_min):
        bad("%s must be greater than %s" % (name, exclusive_min))
    if maximum is not None and number > dec(maximum):
        bad("%s must be at most %s" % (name, maximum))
    return number


def req_num(data, name, **kwargs):
    return check_num(name, req_present(data, name), **kwargs)


def opt_num(data, name, default=None, **kwargs):
    if not _present(data, name):
        return default
    return check_num(name, data[name], **kwargs)


# --------------------------------------------------------------------- booleans
def check_bool(name, value):
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def req_bool(data, name):
    return check_bool(name, req_present(data, name))


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return check_bool(name, data[name])


# -------------------------------------------------------------------- datetimes
def check_dt(name, value):
    try:
        return parse_iso(value)
    except ValueError:
        bad("%s must be an ISO 8601 datetime" % name)


def req_dt(data, name):
    return check_dt(name, req_present(data, name))


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    return check_dt(name, data[name])


def req_month(data, name):
    value = req_present(data, name)
    try:
        parse_year_month(value)
    except ValueError:
        bad("%s must be a YYYY-MM month" % name)
    return value


def req_id(data, name):
    """A foreign-key field: must be present and a string."""
    value = req_present(data, name)
    if not isinstance(value, str) or not value.strip():
        bad("%s must be a non-empty identifier" % name)
    return value


def opt_id(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        bad("%s must be a non-empty identifier" % name)
    return value


def req_str_list(data, name, *, min_items=None, max_items=None, distinct=False,
                 max_len=None):
    value = req_present(data, name)
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if min_items is not None and len(value) < min_items:
        bad("%s must contain at least %d entries" % (name, min_items))
    if max_items is not None and len(value) > max_items:
        bad("%s must contain at most %d entries" % (name, max_items))
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("%s entries must be non-empty strings" % name)
        if max_len is not None and len(item) > max_len:
            bad("%s entries must be at most %d characters" % (name, max_len))
    if distinct and len(set(value)) != len(value):
        bad("%s entries must be distinct" % name)
    return value


# ------------------------------------------------------------------ query strings
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be at least 0")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("%s filter must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s filter must be a boolean" % name)


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        bad("%s filter must be an integer" % name)


def q_month(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        parse_year_month(value)
    except ValueError:
        bad("%s filter must be a YYYY-MM month" % name)
    return value


def q_dt(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        bad("%s filter must be an ISO 8601 datetime" % name)
