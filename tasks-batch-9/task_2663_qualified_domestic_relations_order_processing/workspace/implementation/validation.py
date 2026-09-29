"""Request-shape validation — rung 3 of the ladder (PRD 2.8).

Every violation here is ERR_INVALID_REQUEST (400). This module knows nothing
about persistence, so it can be run before any existence lookup.
"""
from flask import request

from errors import bad_request
from timeutil import parse_date, parse_instant

MISSING = object()


def body():
    """The request body as a dict. A non-object or unparseable body is 400."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body must be valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("Request body must be a JSON object.")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def require_present(data, name):
    if not _present(data, name):
        bad_request("Field '%s' is required." % name)


def _check_string(value, name, min_len, max_len, non_blank):
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if len(value) < min_len or len(value) > max_len:
        bad_request("Field '%s' must be %d..%d characters." % (name, min_len, max_len))
    if non_blank and not value.strip():
        bad_request("Field '%s' must not be blank." % name)
    return value


def req_string(data, name, min_len=1, max_len=120, non_blank=True):
    require_present(data, name)
    return _check_string(data[name], name, min_len, max_len, non_blank)


def opt_string(data, name, min_len=1, max_len=120, non_blank=True, default=None):
    if not _present(data, name):
        return default
    return _check_string(data[name], name, min_len, max_len, non_blank)


def _check_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %d." % (name, maximum))
    return value


def req_int(data, name, minimum=None, maximum=None):
    require_present(data, name)
    return _check_int(data[name], name, minimum, maximum)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        return default
    return _check_int(data[name], name, minimum, maximum)


def _check_bool(value, name):
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def req_bool(data, name):
    require_present(data, name)
    return _check_bool(data[name], name)


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return _check_bool(data[name], name)


def _check_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_enum(data, name, allowed):
    require_present(data, name)
    return _check_enum(data[name], name, allowed)


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return _check_enum(data[name], name, allowed)


def req_date(data, name):
    require_present(data, name)
    return _check_date(data[name], name)


def _check_date(value, name):
    parsed = parse_date(value)
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
    return parsed


def opt_date(data, name, default=None):
    if not _present(data, name):
        return default
    return _check_date(data[name], name)


def req_instant(data, name):
    require_present(data, name)
    parsed = parse_instant(data[name])
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def req_enum_array(data, name, allowed, non_empty=True):
    require_present(data, name)
    return _check_enum_array(data[name], name, allowed, non_empty)


def opt_enum_array(data, name, allowed, non_empty=False, default=None):
    if not _present(data, name):
        return list(default) if default is not None else None
    return _check_enum_array(data[name], name, allowed, non_empty)


def _check_enum_array(value, name, allowed, non_empty):
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % name)
    if non_empty and not value:
        bad_request("Field '%s' must not be empty." % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad_request("Field '%s' items must be one of %s." % (name, ", ".join(sorted(allowed))))
        if item in seen:
            bad_request("Field '%s' must not contain duplicates." % name)
        seen.add(item)
    return list(value)


def query_enum(name, allowed):
    """An optional list filter drawn from a declared enum."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad_request("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    body_text = text[1:] if text.startswith("-") else text
    if not body_text.isdigit():
        bad_request("Query parameter '%s' must be an integer." % name)
    return int(text)


def query_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        bad_request("Query parameter '%s' must be an ISO 8601 calendar date." % name)
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw
