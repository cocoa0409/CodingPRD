"""Body-field validation — PRD §2.5 rule 11 (ERR_INVALID_REQUEST, 400).

Required fields must be present, enums inside their declared set, numbers
inside their declared range and datetimes ISO 8601 UTC.
"""

from flask import request

from errors import ApiError
from util import parse_dt

MISSING = object()


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def _present(body, name):
    return name in body and body[name] is not None


# --------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------

def req_string(body, name):
    if not _present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def opt_string(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(body, name, minimum=None, maximum=None, multiple_of=None):
    if not _present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not _is_int(value):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    if multiple_of is not None and value % multiple_of != 0:
        _bad(name, "must be a whole multiple of %s" % multiple_of)
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None, multiple_of=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum, maximum, multiple_of)


def req_number(body, name, minimum=None, exclusive_minimum=None):
    if not _present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not _is_num(value):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad(name, "must be > %s" % exclusive_minimum)
    return value


def opt_number(body, name, default=None, minimum=None, exclusive_minimum=None):
    if not _present(body, name):
        return default
    return req_number(body, name, minimum, exclusive_minimum)


# --------------------------------------------------------------------------
# Booleans, datetimes, lists
# --------------------------------------------------------------------------

def req_bool(body, name):
    if not _present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_datetime(body, name):
    if not _present(body, name):
        _bad(name, "is required")
    parsed = parse_dt(body[name])
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC datetime")
    return parsed


def opt_datetime(body, name, default=None):
    if not _present(body, name):
        return default
    return req_datetime(body, name)


def req_id(body, name):
    """A foreign-key reference: must be a non-empty string when supplied."""
    return req_string(body, name)


def opt_id(body, name, default=None):
    return opt_string(body, name, default)


def req_string_list(body, name, allowed=None, non_empty=True):
    if not _present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be a list")
    if non_empty and len(value) == 0:
        _bad(name, "must be a non-empty list")
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            _bad(name, "must contain non-empty strings")
        if allowed is not None and item not in allowed:
            _bad(name, "may only contain %s" % ", ".join(allowed))
    return value


def req_object_list(body, name):
    if not _present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be a list")
    if len(value) == 0:
        _bad(name, "must be a non-empty list")
    for item in value:
        if not isinstance(item, dict):
            _bad(name, "must contain objects")
    return value


# --------------------------------------------------------------------------
# List filtering
# --------------------------------------------------------------------------

def qfilter(rows, *names):
    """Apply equality filters taken from the query string. Values are compared
    as strings, so an unknown enum value simply matches nothing rather than
    rejecting the request."""
    out = rows
    for name in names:
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        out = [r for r in out if r.get(name) is not None and str(r.get(name)) == raw]
    return out


def qfilter_bool(rows, name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return rows
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        wanted = True
    elif lowered in ("false", "0"):
        wanted = False
    else:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be true or false" % name)
    return [r for r in rows if bool(r.get(name)) is wanted]
