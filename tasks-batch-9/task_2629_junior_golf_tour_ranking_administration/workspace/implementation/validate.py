"""Request schema validation helpers. Every failure is ERR_INVALID_REQUEST (422)."""
from flask import request

from errors import ApiError
from store import parse_date_str, parse_dt_str, iso

BOOL = (bool,)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Return the JSON body as a dict; an absent body behaves as {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body is not valid JSON")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object")
    return payload


def present(b, name):
    return name in b and b[name] is not None


def req_str(b, name, min_len=1, max_len=None):
    if not present(b, name):
        bad("Field '%s' is required" % name)
    value = b[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters" % (name, max_len))
    return value


def opt_str(b, name, min_len=1, max_len=None, default=None):
    if not present(b, name):
        return default
    return req_str(b, name, min_len, max_len)


def req_enum(b, name, values):
    value = req_str(b, name, min_len=None)
    if value not in values:
        bad("Field '%s' must be one of %s" % (name, ", ".join(sorted(values))))
    return value


def opt_enum(b, name, values, default=None):
    if not present(b, name):
        return default
    return req_enum(b, name, values)


def _check_int(name, value, minimum, maximum):
    if isinstance(value, BOOL) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s" % (name, maximum))
    return value


def req_int(b, name, minimum=None, maximum=None):
    if not present(b, name):
        bad("Field '%s' is required" % name)
    return _check_int(name, b[name], minimum, maximum)


def opt_int(b, name, minimum=None, maximum=None, default=None):
    if not present(b, name):
        return default
    return _check_int(name, b[name], minimum, maximum)


def _check_num(name, value, minimum, maximum):
    if isinstance(value, BOOL) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % name)
    value = float(value)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s" % (name, maximum))
    return value


def req_num(b, name, minimum=None, maximum=None):
    if not present(b, name):
        bad("Field '%s' is required" % name)
    return _check_num(name, b[name], minimum, maximum)


def opt_num(b, name, minimum=None, maximum=None, default=None):
    if not present(b, name):
        return default
    return _check_num(name, b[name], minimum, maximum)


def req_bool(b, name):
    if not present(b, name):
        bad("Field '%s' is required" % name)
    if not isinstance(b[name], BOOL):
        bad("Field '%s' must be a boolean" % name)
    return b[name]


def opt_bool(b, name, default=None):
    if not present(b, name):
        return default
    return req_bool(b, name)


def req_date(b, name):
    value = req_str(b, name, min_len=None)
    if parse_date_str(value) is None:
        bad("Field '%s' must be a YYYY-MM-DD date" % name)
    return value


def opt_date(b, name, default=None):
    if not present(b, name):
        return default
    return req_date(b, name)


def req_dt(b, name):
    """Validate an ISO 8601 instant and normalise it to canonical UTC form."""
    value = req_str(b, name, min_len=None)
    parsed = parse_dt_str(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC timestamp" % name)
    return iso(parsed)


def opt_dt(b, name, default=None):
    if not present(b, name):
        return default
    return req_dt(b, name)


def req_id(b, name):
    return req_str(b, name, min_len=1)


def opt_id(b, name, default=None):
    if not present(b, name):
        return default
    return req_str(b, name, min_len=1)


def pagination():
    """Parse and validate limit/offset from the query string."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit", "").strip()
        try:
            limit = int(raw, 10)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset", "").strip()
        try:
            offset = int(raw, 10)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must be 0 or greater")
    return limit, offset


def filters(*names):
    """Collected non-empty query filters by name."""
    out = {}
    for name in names:
        if name in request.args:
            value = request.args.get(name)
            if value is not None and value != "":
                out[name] = value
    return out
