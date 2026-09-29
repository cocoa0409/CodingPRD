"""Request-shape validation (PRD 2.8 step 3 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import err
from store import D, parse_date, parse_dt

_MISSING = object()


def body():
    if not request.data:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _bad(name, why):
    return err("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def _get(data, name, required, default):
    if name not in data or data[name] is None:
        if required:
            raise _bad(name, "is required.")
        return _MISSING if default is _MISSING else default
    return data[name]


def v_str(data, name, required=True, default=_MISSING, allow_empty=False):
    value = _get(data, name, required, default)
    if value is _MISSING or (not required and name not in data):
        return value if value is not _MISSING else None
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad(name, "must be a string.")
    if not allow_empty and value.strip() == "":
        raise _bad(name, "must not be empty.")
    return value


def v_enum(data, name, allowed, required=True, default=_MISSING):
    value = _get(data, name, required, default)
    if value is _MISSING:
        return None
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise _bad(name, "must be one of %s." % ", ".join(allowed))
    return value


def v_bool(data, name, required=False, default=_MISSING):
    value = _get(data, name, required, default)
    if value is _MISSING:
        return None
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _bad(name, "must be a boolean.")
    return value


def v_int(data, name, required=True, default=_MISSING, minimum=None, maximum=None):
    value = _get(data, name, required, default)
    if value is _MISSING:
        return None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(name, "must be an integer.")
    if minimum is not None and value < minimum:
        raise _bad(name, "is below its minimum.")
    if maximum is not None and value > maximum:
        raise _bad(name, "is above its maximum.")
    return value


def v_num(data, name, required=True, default=_MISSING, minimum=None, maximum=None,
          exclusive_min=None):
    value = _get(data, name, required, default)
    if value is _MISSING:
        return None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(name, "must be a number.")
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        raise _bad(name, "is below its minimum.")
    if exclusive_min is not None and dec <= D(exclusive_min):
        raise _bad(name, "is below its minimum.")
    if maximum is not None and dec > D(maximum):
        raise _bad(name, "is above its maximum.")
    return value


def v_datetime(data, name, required=True, default=_MISSING):
    value = _get(data, name, required, default)
    if value is _MISSING or value is None:
        return None
    parsed = parse_dt(value)
    if parsed is None:
        raise _bad(name, "must be an ISO 8601 UTC instant.")
    return parsed


def v_date(data, name, required=True, default=_MISSING):
    value = _get(data, name, required, default)
    if value is _MISSING or value is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise _bad(name, "must be an ISO 8601 date (YYYY-MM-DD).")
    return parsed


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
