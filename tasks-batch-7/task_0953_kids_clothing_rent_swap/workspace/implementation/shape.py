"""Request-shape validation (PRD 2.9).

Default route for EVERY field-shape failure is ERR_VALIDATION (422).
`enum_in` is used ONLY for the closed list of fields PRD 2.9 routes to
ERR_INVALID_ENUM; every other constrained field uses `member_in`, which routes
to ERR_VALIDATION.
"""

from flask import request

import timeutil
from errors import ApiError

_MISSING = object()


def body_json():
    """Parse the JSON body; a missing body is an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def _bad(name, why):
    return ApiError("ERR_VALIDATION", "%s %s." % (name, why))


def req(body, name):
    if name not in body or body[name] is None:
        raise _bad(name, "is required")
    return body[name]


def opt(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def string(body, name, required=True, default=None, allow_empty=False):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        raise _bad(name, "may not be empty")
    return value


def integer(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        raise _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        raise _bad(name, "must be at most %s" % maximum)
    return value


def number(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        raise _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        raise _bad(name, "must be at most %s" % maximum)
    return value


def boolean(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise _bad(name, "must be a boolean")
    return value


def instant(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad(name, "must be an ISO 8601 string")
    return timeutil.parse_instant(value)


def id_string(body, name, required=True, default=None):
    return string(body, name, required=required, default=default)


def str_list(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, list):
        raise _bad(name, "must be an array")
    for entry in value:
        if not isinstance(entry, str) or entry.strip() == "":
            raise _bad(name, "must be an array of non-empty strings")
    return value


def enum_in(body, name, members, required=True, default=None):
    """CLOSED ERR_INVALID_ENUM list only (PRD 2.9)."""
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad(name, "must be a string")
    if value not in members:
        raise ApiError("ERR_INVALID_ENUM", "%s is not a declared value." % name)
    return value


def member_in(body, name, members, required=True, default=None):
    """Constrained field that is NOT on the ERR_INVALID_ENUM list."""
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad(name, "must be a string")
    if value not in members:
        raise _bad(name, "is not a declared value")
    return value


def query_member(name, members):
    """A list-endpoint filter parameter: out-of-set routes to ERR_VALIDATION."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        raise ApiError("ERR_VALIDATION", "%s is not a declared value." % name)
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
