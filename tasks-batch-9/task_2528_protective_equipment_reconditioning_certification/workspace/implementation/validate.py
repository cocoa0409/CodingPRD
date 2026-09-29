"""Request-schema validation — rung 4 of the rejection ladder (PRD 2.7)."""
from flask import request

from errors import ApiError
from util import parse_dt

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON request body as a dict; an absent body is an empty object."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        _bad("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if not present(data, name):
        _bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        _bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, min_len=None, max_len=None, default=None):
    if not present(data, name):
        return default
    return req_str(data, name, min_len=min_len, max_len=max_len)


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        _bad("%s is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be <= %s." % (name, maximum))
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_num(data, name, minimum=None, maximum=None):
    if not present(data, name):
        _bad("%s is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("%s must be a number." % name)
    if minimum is not None and value < minimum:
        _bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be <= %s." % (name, maximum))
    return value


def req_bool(data, name):
    if not present(data, name):
        _bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    return req_bool(data, name)


def req_enum(data, name, values):
    value = req_str(data, name)
    if value not in values:
        _bad("%s must be one of %s." % (name, ", ".join(values)))
    return value


def opt_enum(data, name, values, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, values)


def req_dt(data, name):
    """A required ISO 8601 instant; returns (datetime, raw_string)."""
    value = req_str(data, name)
    parsed = parse_dt(value)
    if parsed is None:
        _bad("%s must be an ISO 8601 datetime." % name)
    return parsed, value


def opt_dt(data, name):
    if not present(data, name):
        return None, None
    return req_dt(data, name)


def req_window(data, start_name="window_start", end_name="window_end"):
    """A window whose end must fall strictly after its start."""
    start, start_raw = req_dt(data, start_name)
    end, end_raw = req_dt(data, end_name)
    if end <= start:
        _bad("%s must be strictly after %s." % (end_name, start_name))
    return (start, start_raw), (end, end_raw)


def req_id(data, name):
    """A required foreign-key identifier field."""
    return req_str(data, name)


def opt_id(data, name):
    return opt_str(data, name)


def query_enum(name, values):
    """An optional query-string filter constrained to an enum set."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        _bad("%s must be one of %s." % (name, ", ".join(values)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
