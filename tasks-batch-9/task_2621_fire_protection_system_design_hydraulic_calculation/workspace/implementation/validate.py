"""Request-shape validation (admission order step 9) and pagination (PRD 2.3).

Every violation here raises ERR_INVALID_REQUEST (HTTP 422).
"""
from flask import request

from errors import ApiError
from utils import is_int, is_number, parse_dt

MISSING = object()


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    """The parsed JSON object body; a missing body is an empty object."""
    try:
        raw = request.get_json(silent=True, force=True)
    except Exception:
        raw = None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _bad("The request body must be a JSON object.")
    return raw


def raw_fk(data, field):
    """A foreign key value usable for existence checking (admission step 5).

    Absent, null or non-string values are left for the schema check at step 9.
    """
    value = data.get(field, MISSING)
    if value is MISSING or value is None or not isinstance(value, str):
        return None
    return value


def req_str(data, field, enum=None, length=None):
    if field not in data:
        _bad("Field '%s' is required." % field)
    value = data.get(field)
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field)
    if not value.strip():
        _bad("Field '%s' must not be blank." % field)
    if enum is not None and value not in enum:
        _bad("Field '%s' must be one of %s." % (field, ", ".join(enum)))
    if length is not None and len(value) != length:
        _bad("Field '%s' must be exactly %d characters." % (field, length))
    return value


def opt_str(data, field, enum=None, default=None, length=None):
    if field not in data or data.get(field) is None:
        return default
    return req_str(data, field, enum=enum, length=length)


def state_code(data, field, required=True, default=None):
    """Exactly two uppercase letters of the USPS state code."""
    if not required and (field not in data or data.get(field) is None):
        return default
    value = req_str(data, field, length=2)
    if not (value.isalpha() and value.isupper()):
        _bad("Field '%s' must be exactly two uppercase letters." % field)
    return value


def req_num(data, field, gt=None, ge=None, lt=None, le=None):
    if field not in data:
        _bad("Field '%s' is required." % field)
    value = data.get(field)
    if not is_number(value):
        _bad("Field '%s' must be a number." % field)
    _range(field, value, gt, ge, lt, le)
    return float(value)


def opt_num(data, field, gt=None, ge=None, lt=None, le=None, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_num(data, field, gt=gt, ge=ge, lt=lt, le=le)


def req_int(data, field, gt=None, ge=None, lt=None, le=None):
    if field not in data:
        _bad("Field '%s' is required." % field)
    value = data.get(field)
    if not is_int(value):
        _bad("Field '%s' must be an integer." % field)
    _range(field, value, gt, ge, lt, le)
    return int(value)


def opt_int(data, field, gt=None, ge=None, lt=None, le=None, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, gt=gt, ge=ge, lt=lt, le=le)


def _range(field, value, gt, ge, lt, le):
    if gt is not None and not value > gt:
        _bad("Field '%s' must be greater than %s." % (field, gt))
    if ge is not None and not value >= ge:
        _bad("Field '%s' must not be less than %s." % (field, ge))
    if lt is not None and not value < lt:
        _bad("Field '%s' must be less than %s." % (field, lt))
    if le is not None and not value <= le:
        _bad("Field '%s' must not be greater than %s." % (field, le))


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    value = data.get(field)
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % field)
    return value


def req_dt(data, field):
    if field not in data:
        _bad("Field '%s' is required." % field)
    value = data.get(field)
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO 8601 timestamp string." % field)
    parsed = parse_dt(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 timestamp string." % field)
    return parsed


def req_id_list(data, field):
    if field not in data:
        _bad("Field '%s' is required." % field)
    value = data.get(field)
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % field)
    if not value:
        _bad("Field '%s' must not be empty." % field)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad("Field '%s' must contain non-blank strings." % field)
    if len(set(value)) != len(value):
        _bad("Field '%s' must not contain duplicates." % field)
    return list(value)


LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _bad("Query parameter '%s' must be an integer." % name)
    if value < minimum:
        _bad("Query parameter '%s' must not be less than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Query parameter '%s' must not exceed %d." % (name, maximum))
    return value


def pagination():
    """(limit, offset) from the query string, validated against PRD 2.3."""
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN)
    return limit, offset


def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad("Query parameter '%s' must be a boolean." % name)
