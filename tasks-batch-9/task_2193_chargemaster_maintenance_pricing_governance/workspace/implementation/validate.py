"""Payload schema conformance helpers — validation rank 11 (ERR_VALIDATION)."""

from flask import request

from errors import fail
from store import parse_iso

_MISSING = object()


def body():
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def present(data, name):
    return name in data and data[name] is not None


def _bad(name, why):
    fail("ERR_VALIDATION", "Field '%s' %s." % (name, why))


def req_string(data, name, min_len=1):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, str) or len(value) < min_len:
        _bad(name, "must be a string of at least %d characters" % min_len)
    return value


def opt_string(data, name, default=None, min_len=1):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str) or len(value) < min_len:
        _bad(name, "must be a string of at least %d characters" % min_len)
    return value


def req_int(data, name, minimum=0):
    if not present(data, name):
        _bad(name, "is required")
    return _as_int(data, name, minimum)


def opt_int(data, name, default=None, minimum=0):
    if name not in data or data[name] is None:
        return default
    return _as_int(data, name, minimum)


def _as_int(data, name, minimum):
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    return value


def req_bool(data, name):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_enum(data, name, members):
    value = req_string(data, name)
    if value not in members:
        _bad(name, "must be one of %s" % ", ".join(members))
    return value


def opt_enum(data, name, members, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str) or value not in members:
        _bad(name, "must be one of %s" % ", ".join(members))
    return value


def req_dt(data, name):
    if not present(data, name):
        _bad(name, "is required")
    return _as_dt(data, name)


def opt_dt(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return _as_dt(data, name)


def _as_dt(data, name):
    value = data[name]
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        _bad(name, "must be a well-formed ISO 8601 UTC datetime")
    return parsed


def opt_id(data, name):
    """An optional foreign-key string; absent or null returns None."""
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str) or not value:
        _bad(name, "must be a string identifier")
    return value


def req_id(data, name):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, str) or not value:
        _bad(name, "must be a string identifier")
    return value


def opt_str_list(data, name, default=None, members=None):
    if name not in data or data[name] is None:
        return default
    return _as_str_list(data, name, members)


def req_str_list(data, name, members=None):
    if not present(data, name):
        _bad(name, "is required")
    return _as_str_list(data, name, members)


def _as_str_list(data, name, members):
    value = data[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    for element in value:
        if not isinstance(element, str):
            _bad(name, "must be an array of strings")
        if members is not None and element not in members:
            _bad(name, "may only contain %s" % ", ".join(members))
    return list(value)


def markup_tiers(data, name, default=None):
    """Ordered array of { min_cost_basis_cents, markup_bp }."""
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    tiers = []
    previous = None
    for index, element in enumerate(value):
        if not isinstance(element, dict):
            _bad(name, "must be an array of objects")
        floor = element.get("min_cost_basis_cents")
        bp = element.get("markup_bp")
        for key, val in (("min_cost_basis_cents", floor), ("markup_bp", bp)):
            if isinstance(val, bool) or not isinstance(val, int):
                _bad(name, "entries need an integer %s" % key)
            if val < 0:
                _bad(name, "entries need a non-negative %s" % key)
        if index == 0 and floor != 0:
            _bad(name, "first tier must have min_cost_basis_cents == 0")
        if previous is not None and floor < previous:
            _bad(name, "must be sorted ascending by min_cost_basis_cents")
        previous = floor
        tiers.append({"min_cost_basis_cents": floor, "markup_bp": bp})
    return tiers


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "Query parameter '%s' must be a boolean." % name)


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    text = value.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)
