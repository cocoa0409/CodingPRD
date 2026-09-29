"""Request-shape validation (step 3 of the rejection ladder).

Every failure here is ERR_INVALID_REQUEST / 400.
"""

from flask import request

import db
from errors import ApiError

MAX_LIMIT = 100
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field, min_len=1, max_len=None):
    value = data.get(field)
    if not isinstance(value, str):
        bad("%s is required and must be a string." % field)
    if len(value.strip()) < min_len:
        bad("%s must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (field, max_len))
    return value


def opt_str(data, field, default=None, min_len=0):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if min_len and len(value.strip()) < min_len:
        bad("%s must be at least %d characters." % (field, min_len))
    return value


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if not is_int(value):
        bad("%s is required and must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (field, maximum))
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        bad("%s is required and must be a boolean." % field)
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_bool(data, field)


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def req_dt(data, field):
    value = data.get(field)
    if not isinstance(value, str):
        bad("%s is required and must be an ISO 8601 timestamp." % field)
    try:
        db.parse_dt(value)
    except Exception:
        bad("%s must be a valid ISO 8601 timestamp." % field)
    return value


def opt_dt(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_dt(data, field)


def req_id(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        bad("%s is required and must be a string identifier." % field)
    return value


def req_code_list(data, field, allowed=None, min_len=1):
    value = data.get(field)
    if not isinstance(value, list) or len(value) < min_len:
        bad("%s must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("%s entries must be strings." % field)
        if allowed is not None and item not in allowed:
            bad("%s contains an unsupported value: %s." % (field, item))
    return list(value)


def req_str_list(data, field, min_len=1):
    value = data.get(field)
    if not isinstance(value, list) or len(value) < min_len:
        bad("%s must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("%s entries must be strings." % field)
    return list(value)


# ------------------------------------------------------------------ paging


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        bad("%s must be an integer." % name)
    value = int(text)
    if value < minimum:
        bad("%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _query_int("offset", DEFAULT_OFFSET, 0)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def query_int(name, default=None, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        bad("%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (name, maximum))
    return value


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0"):
        return False
    bad("%s must be a boolean." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
