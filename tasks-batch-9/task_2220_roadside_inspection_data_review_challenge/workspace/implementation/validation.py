"""Request-shape validation (tier 3 of PRD 2.8). Everything here is ERR_INVALID_REQUEST."""

from flask import request

from db import parse_ts
from errors import err


def bad(message):
    return err("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body; an absent body is an empty mapping."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise bad("Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def _present(b, name):
    return name in b and b[name] is not None


def get_str(b, name, required=True, default=None, max_len=None, min_len=1):
    if not _present(b, name):
        if required:
            raise bad("'%s' is required." % name)
        return default
    value = b[name]
    if not isinstance(value, str):
        raise bad("'%s' must be a string." % name)
    if len(value.strip()) < min_len:
        raise bad("'%s' must not be empty." % name)
    if max_len is not None and len(value) > max_len:
        raise bad("'%s' must be at most %d characters." % (name, max_len))
    return value


def get_enum(b, name, allowed, required=True, default=None):
    if not _present(b, name):
        if required:
            raise bad("'%s' is required." % name)
        return default
    value = b[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def get_int(b, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(b, name):
        if required:
            raise bad("'%s' is required." % name)
        return default
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("'%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("'%s' must be <= %s." % (name, maximum))
    return value


def get_num(b, name, required=True, default=None, minimum=None, maximum=None,
            exclusive_min=None):
    if not _present(b, name):
        if required:
            raise bad("'%s' is required." % name)
        return default
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("'%s' must be a number." % name)
    value = float(value)
    if minimum is not None and value < minimum:
        raise bad("'%s' must be >= %s." % (name, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        raise bad("'%s' must be > %s." % (name, exclusive_min))
    if maximum is not None and value > maximum:
        raise bad("'%s' must be <= %s." % (name, maximum))
    return value


def get_bool(b, name, required=True, default=None):
    if not _present(b, name):
        if required:
            raise bad("'%s' is required." % name)
        return default
    value = b[name]
    if not isinstance(value, bool):
        raise bad("'%s' must be a boolean." % name)
    return value


def get_dt(b, name, required=True, default=None):
    if not _present(b, name):
        if required:
            raise bad("'%s' is required." % name)
        return default
    value = b[name]
    if not isinstance(value, str):
        raise bad("'%s' must be an ISO 8601 datetime string." % name)
    try:
        return parse_ts(value)
    except Exception:
        raise bad("'%s' must be an ISO 8601 datetime string." % name)


def forbid(b, name, reason):
    if name in b and b[name] is not None:
        raise bad("'%s' %s" % (name, reason))


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------

def _query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise bad("'%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise bad("'%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)


def pagination():
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = 10
    elif limit < 1 or limit > 100:
        raise bad("'limit' must be between 1 and 100.")
    if offset is None:
        offset = 0
    elif offset < 0:
        raise bad("'offset' must not be negative.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad("'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("'%s' must be a boolean." % name)
