"""Request-shape validation — ladder rung 14, ERR_INVALID_REQUEST (PRD §2.9)."""

from flask import request

from errors import ApiError
from util import parse_dt

BAD = "ERR_INVALID_REQUEST"


def bad(msg):
    raise ApiError(BAD, msg)


def body():
    """Parse the JSON body permissively; a non-object body is an empty dict."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def raw_str(data, key):
    """Return the value only when it is a non-empty string, else None."""
    v = data.get(key)
    if isinstance(v, str) and v.strip():
        return v
    return None


def req_str(data, key, min_len=1, max_len=None, allow_blank=False):
    v = data.get(key)
    if not isinstance(v, str):
        bad("Field '%s' is required and must be a string." % key)
    if not allow_blank and not v.strip():
        bad("Field '%s' must not be blank." % key)
    if len(v) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(v) > max_len:
        bad("Field '%s' is too long." % key)
    return v


def opt_str(data, key, default=None, max_len=None):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not isinstance(v, str):
        bad("Field '%s' must be a string." % key)
    if max_len is not None and len(v) > max_len:
        bad("Field '%s' is too long." % key)
    return v


def req_enum(data, key, members):
    v = data.get(key)
    if not isinstance(v, str) or v not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(members))))
    return v


def opt_enum(data, key, members, default=None):
    if key not in data or data.get(key) is None:
        return default
    return req_enum(data, key, members)


def _as_int(v, key):
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field '%s' must be an integer." % key)
    return v


def req_int(data, key, minimum=None, maximum=None):
    if key not in data:
        bad("Field '%s' is required." % key)
    v = _as_int(data.get(key), key)
    _range(v, key, minimum, maximum)
    return v


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data.get(key) is None:
        return default
    v = _as_int(data.get(key), key)
    _range(v, key, minimum, maximum)
    return v


def _range(v, key, minimum, maximum):
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))


def req_dt(data, key):
    if key not in data:
        bad("Field '%s' is required." % key)
    dt = parse_dt(data.get(key))
    if dt is None:
        bad("Field '%s' must be a valid ISO 8601 UTC instant." % key)
    return dt


def opt_dt(data, key, default=None):
    if key not in data or data.get(key) is None:
        return default
    return req_dt(data, key)


def req_email(data, key):
    v = req_str(data, key)
    if "@" not in v:
        bad("Field '%s' must contain '@'." % key)
    return v


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, members):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in members:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(members))))
    return v


def query_str(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v


def page(items, limit, offset):
    return items[offset:offset + limit]
