"""Band 2 request-schema validation helpers.  Every failure is ERR_INVALID_REQUEST."""
from flask import request

import util
from errors import err

_MISSING = object()


def body():
    if request.content_length in (None, 0):
        raw = None
    else:
        raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        raise err("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if len(value.strip()) == 0:
        raise err("ERR_INVALID_REQUEST", "%s must not be blank." % key)
    if len(value) < min_len:
        raise err("ERR_INVALID_REQUEST", "%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise err("ERR_INVALID_REQUEST", "%s must be at most %d characters." % (key, max_len))
    return value


def opt_str(data, key, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len, max_len)


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        raise err("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "%s must be <= %d." % (key, maximum))
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum, maximum)


def req_bool(data, key):
    if not _present(data, key):
        raise err("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def req_enum(data, key, allowed):
    value = req_str(data, key, 1, None)
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_dt(data, key):
    if not _present(data, key):
        raise err("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    parsed = util.parse_iso(value)
    if parsed is None:
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC timestamp." % key)
    return parsed


def req_id(data, key):
    if not _present(data, key):
        raise err("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return value


def opt_id(data, key):
    if not _present(data, key):
        return None
    return req_id(data, key)


def pagination():
    """limit 1..100 (default 10), offset >= 0 (default 0); PRD 2.3."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def bool_filter(name):
    """Optional boolean query filter; returns None when absent."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise err("ERR_INVALID_REQUEST", "%s must be true or false." % name)


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
