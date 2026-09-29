"""Request-shape screening (ladder step 4) and window validity (ladder step 5)."""
from flask import request

from common import fail, parse_instant, is_whole_minute

_MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(data, name, required):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Missing required field '%s'." % name)
        return _MISSING
    return data[name]


def want_str(data, name, required=True, min_len=None, max_len=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    return value


def want_int(data, name, required=True, minimum=None, maximum=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % name)
    return value


def want_bool(data, name, required=True):
    value = _present(data, name, required)
    if value is _MISSING:
        return None
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def want_enum(data, name, allowed, required=True):
    value = _present(data, name, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a recognised value." % name)
    return value


def want_window_raw(data, name):
    """A window endpoint must be present and a string; the instant itself is
    screened later, at ladder step 5."""
    value = _present(data, name, True)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def screen_window(start_raw, end_raw):
    """Ladder step 5: whole-minute UTC endpoints, start strictly before end."""
    start = parse_instant(start_raw)
    end = parse_instant(end_raw)
    if start is None or end is None:
        fail("ERR_INVALID_WINDOW", "Window endpoints must be ISO 8601 UTC instants.")
    if not is_whole_minute(start) or not is_whole_minute(end):
        fail("ERR_INVALID_WINDOW", "Window endpoints must be aligned to whole minutes.")
    if not start < end:
        fail("ERR_INVALID_WINDOW", "Window start must be strictly before its end.")
    return start, end
