"""Request-shape validation (PRD 2.10 band 3 -- ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import bad_request
from timeutil import parse_date, parse_dt, parse_hhmm

_MISSING = object()


def body():
    """Parse the JSON body.  A missing body is treated as an empty object so
    that endpoints with only optional fields still work."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data and request.data.strip():
            bad_request("Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        bad_request("Request body must be a JSON object.")
    return data


def _present(data, key):
    return isinstance(data, dict) and key in data and data[key] is not None


def req_str(data, key, allow_empty=True):
    if not _present(data, key):
        bad_request("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if not allow_empty and not value.strip():
        bad_request("Field '%s' must not be empty." % key)
    return value


def opt_str(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    return value


def _as_int(value, key):
    if isinstance(value, bool):
        bad_request("Field '%s' must be an integer." % key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        bad_request("Field '%s' must be an integer." % key)
    bad_request("Field '%s' must be an integer." % key)


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad_request("Field '%s' is required." % key)
    value = _as_int(data[key], key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    value = _as_int(data[key], key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (key, maximum))
    return value


def _as_decimal(value, key):
    if isinstance(value, bool):
        bad_request("Field '%s' must be a number." % key)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            bad_request("Field '%s' must be a number." % key)
    bad_request("Field '%s' must be a number." % key)


def req_num(data, key, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, key):
        bad_request("Field '%s' is required." % key)
    value = _as_decimal(data[key], key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (key, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        bad_request("Field '%s' must be > %s." % (key, exclusive_min))
    return value


def req_bool(data, key):
    if not _present(data, key):
        bad_request("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def opt_bool(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_date(data, key):
    value = req_str(data, key)
    parsed = parse_date(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 date." % key)
    return parsed


def req_datetime(data, key):
    value = req_str(data, key)
    parsed = parse_dt(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def req_hhmm(data, key):
    value = req_str(data, key)
    parsed = parse_hhmm(value)
    if parsed is None:
        bad_request("Field '%s' must be an 'HH:MM' clock time." % key)
    return parsed


def opt_date_array(data, key):
    if not _present(data, key):
        return []
    value = data[key]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array of ISO 8601 dates." % key)
    out = []
    for item in value:
        parsed = parse_date(item)
        if parsed is None:
            bad_request("Field '%s' must contain only ISO 8601 dates." % key)
        out.append(item.strip())
    return out


def reject_unknown_version_field(data, *fields):
    """No endpoint other than the three declared OCC writes accepts a version
    declaration (PRD 2.9); this helper simply enforces required presence."""
    for field in fields:
        if not _present(data, field):
            bad_request("Field '%s' is required." % field)


# --- pagination (PRD 2.3) --------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _query_int("limit", raw)
        if limit < 1 or limit > 100:
            bad_request("limit must be an integer between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _query_int("offset", raw)
        if offset < 0:
            bad_request("offset must be an integer of 0 or more.")
    return limit, offset


def _query_int(name, raw):
    if raw is None:
        bad_request("%s must be an integer." % name)
    text = raw.strip()
    if not text:
        bad_request("%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        bad_request("%s must be an integer." % name)
    return -int(digits) if negative else int(digits)


def query_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
