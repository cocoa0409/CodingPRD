"""Body / query wellformedness (validation priority 3, PRD 2.6)."""

from flask import request

from errors import ApiError
from store import parse_ts


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("request body must be a JSON object")
    return data


def _is_bool(v):
    return isinstance(v, bool)


def _int_value(v, name):
    if _is_bool(v):
        bad("%s must be an integer" % name)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != int(v):
            bad("%s must be a whole number of cents" % name)
        return int(v)
    bad("%s must be an integer" % name)


def _num_value(v, name):
    if _is_bool(v) or not isinstance(v, (int, float)):
        bad("%s must be a number" % name)
    return v


def present(body, name):
    return name in body and body[name] is not None


def req_raw(body, name):
    if not present(body, name):
        bad("%s is required" % name)
    return body[name]


def req_str(body, name, max_len=None, min_len=1):
    value = req_raw(body, name)
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    stripped = value.strip()
    if len(stripped) < min_len:
        bad("%s must not be blank" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s exceeds %d characters" % (name, max_len))
    return value


def opt_str(body, name, max_len=None, default=None):
    if not present(body, name):
        return default
    return req_str(body, name, max_len=max_len)


def raw_str(body, name, max_len=None):
    """Required string that is allowed to be empty (a downstream rule judges it)."""
    value = req_raw(body, name)
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s exceeds %d characters" % (name, max_len))
    return value


def req_enum(body, name, members):
    value = req_raw(body, name)
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s" % (name, ", ".join(sorted(members))))
    return value


def opt_enum(body, name, members, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, members)


def req_cents(body, name, minimum=0):
    value = _int_value(req_raw(body, name), name)
    if value < minimum:
        bad("%s must be >= %d" % (name, minimum))
    return value


def opt_cents(body, name, minimum=0, default=0):
    if not present(body, name):
        return default
    return req_cents(body, name, minimum=minimum)


def req_int(body, name, minimum=None):
    value = _int_value(req_raw(body, name), name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %d" % (name, minimum))
    return value


def req_qty(body, name):
    return req_int(body, name, minimum=1)


def req_pct(body, name, low=0, high=100):
    value = _num_value(req_raw(body, name), name)
    if value < low or value > high:
        bad("%s must be between %s and %s" % (name, low, high))
    return value


def opt_pct(body, name, low=0, high=100, default=0):
    if not present(body, name):
        return default
    return req_pct(body, name, low=low, high=high)


def opt_bool(body, name, default=False):
    if not present(body, name):
        return default
    value = body[name]
    if not _is_bool(value):
        bad("%s must be a boolean" % name)
    return value


def req_ts(body, name):
    value = req_raw(body, name)
    parsed = parse_ts(value)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant" % name)
    return parsed


def opt_ts(body, name, default=None):
    if not present(body, name):
        return default
    return req_ts(body, name)


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit_value < 1 or limit_value > 100:
            bad("limit must be between 1 and 100")
    if offset is None or offset == "":
        offset_value = 0
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset_value < 0:
            bad("offset must be >= 0")
    return limit_value, offset_value


def query_enum(name, members):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        bad("%s must be one of %s" % (name, ", ".join(sorted(members))))
    return value
