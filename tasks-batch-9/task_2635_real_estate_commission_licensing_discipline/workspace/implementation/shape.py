"""Rung 3 helpers: request-body shape (ERR_INVALID_REQUEST, HTTP 400)."""
from flask import request

import store
from errors import invalid


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        invalid("Request body must be a JSON object.")
    return payload


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field):
    if not present(data, field):
        invalid("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % field)
    return value


def opt_str(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % field)
    return value


def _as_int(field, value):
    if isinstance(value, bool):
        invalid("Field '%s' must be an integer." % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    invalid("Field '%s' must be an integer." % field)


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        invalid("Field '%s' is required." % field)
    value = _as_int(field, data[field])
    _bounds(field, value, minimum, maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    value = _as_int(field, data[field])
    _bounds(field, value, minimum, maximum)
    return value


def _bounds(field, value, minimum, maximum):
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must not exceed %d." % (field, maximum))


def req_bool(data, field):
    if not present(data, field):
        invalid("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % field)
    return value


def req_enum(data, field, members):
    value = req_str(data, field)
    if value not in members:
        invalid("Field '%s' must be one of %s." % (field, ", ".join(sorted(members))))
    return value


def opt_enum(data, field, members, default=None):
    if not present(data, field):
        return default
    value = opt_str(data, field)
    if value not in members:
        invalid("Field '%s' must be one of %s." % (field, ", ".join(sorted(members))))
    return value


def req_date(data, field):
    raw = req_str(data, field)
    try:
        return store.parse_date(raw)
    except Exception:
        invalid("Field '%s' must be an ISO 8601 date." % field)


def opt_date(data, field, default=None):
    if not present(data, field):
        return default
    raw = opt_str(data, field)
    try:
        return store.parse_date(raw)
    except Exception:
        invalid("Field '%s' must be an ISO 8601 date." % field)


def req_dt(data, field):
    raw = req_str(data, field)
    try:
        return store.parse_datetime(raw)
    except Exception:
        invalid("Field '%s' must be an ISO 8601 timestamp." % field)


def opt_dt(data, field, default=None):
    if not present(data, field):
        return default
    raw = opt_str(data, field)
    try:
        return store.parse_datetime(raw)
    except Exception:
        invalid("Field '%s' must be an ISO 8601 timestamp." % field)


def req_id(data, field):
    """A body foreign key: must be a present, non-empty string."""
    value = req_str(data, field)
    if value.strip() == "":
        invalid("Field '%s' is required." % field)
    return value


def opt_id(data, field):
    if not present(data, field):
        return None
    value = opt_str(data, field)
    if value is not None and value.strip() == "":
        return None
    return value


def paging():
    """limit defaults 10 (1..100); offset defaults 0. Out of range clamps."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and str(raw_limit).strip() != "":
        try:
            limit = int(str(raw_limit).strip())
        except Exception:
            limit = 10
        limit = max(1, min(100, limit))
    raw_offset = request.args.get("offset")
    if raw_offset is not None and str(raw_offset).strip() != "":
        try:
            offset = int(str(raw_offset).strip())
        except Exception:
            offset = 0
        offset = max(0, offset)
    return limit, offset
