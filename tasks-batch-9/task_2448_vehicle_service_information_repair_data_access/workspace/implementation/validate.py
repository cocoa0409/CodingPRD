"""Request-shape validation -- ladder rung 6 (PRD 2.7) and PRD 2.3 pagination."""

from flask import request

from errors import err
from store import parse_iso

_INVALID = "ERR_INVALID_REQUEST"


def body_object():
    """Return the request body as a dict; {} when no body was supplied."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        raise err(_INVALID, "The request body must be a JSON object.")
    return data


def check_allowed(body, allowed):
    """No unknown fields (an 'id' supplied by a client is an unknown field)."""
    for key in body:
        if key not in allowed:
            raise err(_INVALID, "Unknown field: %s" % key)


def _present(body, key):
    return key in body and body[key] is not None


def get_str(body, key, min_len=1, max_len=None, required=True, default=None):
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise err(_INVALID, "Field %s must be a string." % key)
    if len(value) < min_len:
        raise err(_INVALID, "Field %s is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise err(_INVALID, "Field %s is longer than %d characters." % (key, max_len))
    return value


def get_int(body, key, minimum=None, maximum=None, required=True, default=None):
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(_INVALID, "Field %s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise err(_INVALID, "Field %s is below its declared minimum %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise err(_INVALID, "Field %s is above its declared maximum %d." % (key, maximum))
    return value


def get_bool(body, key, required=False, default=False):
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise err(_INVALID, "Field %s must be a boolean." % key)
    return value


def get_enum(body, key, members, required=True, default=None):
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in members:
        raise err(_INVALID, "Field %s must be one of %s." % (key, ", ".join(sorted(members))))
    return value


def get_dt(body, key, required=True):
    """Returns (raw_string, datetime); (None, None) when absent and optional."""
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return None, None
    value = body[key]
    parsed = parse_iso(value)
    if parsed is None:
        raise err(_INVALID, "Field %s must be a valid ISO 8601 UTC instant." % key)
    return value, parsed


def get_ref(body, key, required=True, default=None):
    """An identifier-valued field: a non-empty string."""
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not value:
        raise err(_INVALID, "Field %s must be a non-empty string identifier." % key)
    return value


def get_ref_list(body, key, min_items, max_items, required=True):
    if not _present(body, key):
        if required:
            raise err(_INVALID, "Missing required field: %s" % key)
        return None
    value = body[key]
    if not isinstance(value, list):
        raise err(_INVALID, "Field %s must be an array." % key)
    if len(value) < min_items or len(value) > max_items:
        raise err(
            _INVALID,
            "Field %s must hold between %d and %d items." % (key, min_items, max_items),
        )
    for item in value:
        if not isinstance(item, str) or not item:
            raise err(_INVALID, "Field %s must hold non-empty string identifiers." % key)
    if len(set(value)) != len(value):
        raise err(_INVALID, "Field %s must hold distinct identifiers." % key)
    return value


# -- query parameters -----------------------------------------------------


def pagination():
    """limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        limit = _query_int("limit", limit_raw)
        if limit < 1 or limit > 100:
            raise err(_INVALID, "limit must be between 1 and 100.")
    if offset_raw is not None:
        offset = _query_int("offset", offset_raw)
        if offset < 0:
            raise err(_INVALID, "offset must be at least 0.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err(_INVALID, "Query parameter %s must be an integer." % name)


def q_enum(name, members, default=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    if raw not in members:
        raise err(_INVALID, "Query parameter %s must be one of %s." % (name, ", ".join(sorted(members))))
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return _query_int(name, raw)
