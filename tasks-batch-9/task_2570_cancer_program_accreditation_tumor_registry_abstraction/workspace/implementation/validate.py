"""Request-shape validation helpers.  Every failure is ERR_INVALID_REQUEST."""

from flask import request

import db
from errors import ApiError, invalid

MISSING = object()


def body():
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("Body must be a JSON object.")
    return data


def _raw(b, key, required):
    if key not in b or b[key] is None:
        if required:
            raise invalid("Field '%s' is required." % key)
        return MISSING
    return b[key]


def f_str(b, key, required=True, allow_empty=False):
    v = _raw(b, key, required)
    if v is MISSING:
        return None
    if not isinstance(v, str):
        raise invalid("Field '%s' must be a string." % key)
    if not allow_empty and not v.strip():
        raise invalid("Field '%s' must be a non-empty string." % key)
    return v


def f_bool(b, key, required=True, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    if not isinstance(v, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return v


def f_int(b, key, required=True, minimum=None, maximum=None, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("Field '%s' must be an integer." % key)
    if minimum is not None and v < minimum:
        raise invalid("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        raise invalid("Field '%s' must be <= %s." % (key, maximum))
    return v


def f_num(b, key, required=True, minimum=None, maximum=None, default=None,
          exclusive_min=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid("Field '%s' must be a number." % key)
    if minimum is not None and v < minimum:
        raise invalid("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        raise invalid("Field '%s' must be <= %s." % (key, maximum))
    if exclusive_min is not None and v <= exclusive_min:
        raise invalid("Field '%s' must be > %s." % (key, exclusive_min))
    return v


def f_pct(b, key, required=True, default=None):
    return f_num(b, key, required=required, minimum=0, maximum=100,
                 default=default)


def f_enum(b, key, allowed, required=True, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise invalid("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return v


def f_date(b, key, required=True, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    parsed = db.parse_date(v)
    if parsed is None:
        raise invalid("Field '%s' must be an ISO 8601 calendar date." % key)
    return parsed


def f_instant(b, key, required=True, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    parsed = db.parse_instant(v)
    if parsed is None:
        raise invalid("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def f_enum_list(b, key, allowed, required=True, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    if not isinstance(v, list):
        raise invalid("Field '%s' must be an array." % key)
    for member in v:
        if not isinstance(member, str) or member not in allowed:
            raise invalid("Field '%s' members must be one of %s."
                          % (key, sorted(allowed)))
    return list(v)


def f_str_list(b, key, required=True, default=None):
    v = _raw(b, key, required)
    if v is MISSING:
        return default
    if not isinstance(v, list):
        raise invalid("Field '%s' must be an array." % key)
    for member in v:
        if not isinstance(member, str):
            raise invalid("Field '%s' members must be strings." % key)
    return list(v)


# ------------------------------------------------------------ query handling

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _q_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer." % name)
    if str(value) != raw.strip():
        # reject things like "1.0" / "+1 " that int() would swallow oddly
        try:
            if int(raw.strip()) != value:
                raise invalid("Query parameter '%s' is invalid." % name)
        except ValueError:
            raise invalid("Query parameter '%s' is invalid." % name)
    if value < minimum:
        raise invalid("Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def pagination():
    limit = _q_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _q_int("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise invalid("Query parameter '%s' is invalid." % name)
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
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer." % name)
