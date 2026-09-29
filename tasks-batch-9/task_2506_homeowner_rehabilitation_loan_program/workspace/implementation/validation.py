"""Request payload / query-string validation helpers (precedence 4-7)."""

from flask import request

import clock
import errors
from errors import fail

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

_MISSING = object()


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


# --------------------------------------------------------------------------
# path / body foreign keys
# --------------------------------------------------------------------------


def path_row(store, row_id, error_id):
    row = store.get(row_id)
    if row is None:
        fail(error_id)
    return row


def body_fk(body, key, store, error_id):
    """Resolve a body foreign key (precedence 5).

    An absent / null / non-string value is deferred to schema validation so the
    lower-priority ERR_INVALID_REQUEST wins for a malformed payload.
    """
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, str):
        return None
    row = store.get(value)
    if row is None:
        fail(error_id)
    return row


# --------------------------------------------------------------------------
# scalar field validation
# --------------------------------------------------------------------------


def _bad(key, detail):
    fail(errors.ERR_INVALID_REQUEST, "Field '%s' %s." % (key, detail))


def require_present(body, key):
    if key not in body or body[key] is None:
        _bad(key, "is required")
    return body[key]


def field_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        _bad(key, "must be a non-empty string")
    return value


def field_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be at most %s" % maximum)
    return value


def field_number(body, key, required=True, default=None, minimum=None):
    if key not in body or body[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %s" % minimum)
    return value


def field_bool(body, key, required=False, default=False):
    if key not in body or body[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def field_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def field_datetime(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _bad(key, "is required")
        return default
    parsed = clock.parse_datetime(body[key])
    if parsed is None:
        _bad(key, "must be an ISO 8601 timestamp")
    return parsed


def field_id(body, key, required=True, default=None):
    return field_str(body, key, required=required, default=default)


# --------------------------------------------------------------------------
# optimistic concurrency (precedence 7)
# --------------------------------------------------------------------------


def check_version(row, expected):
    if expected is None:
        return
    if row.get("version") != expected:
        fail(errors.ERR_STALE_VERSION)


# --------------------------------------------------------------------------
# pagination + filters
# --------------------------------------------------------------------------


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' is out of range." % name)
    return value


def filter_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_enum(name, allowed):
    raw = filter_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' is not a valid value." % name)
    return raw


def filter_int(name):
    raw = filter_str(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer." % name)


def filter_bool(name):
    raw = filter_str(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' must be a boolean." % name)
