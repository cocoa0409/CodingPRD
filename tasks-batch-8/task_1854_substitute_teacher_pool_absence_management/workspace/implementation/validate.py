"""Pipeline stage 2: request body shape validation (ERR_INVALID_REQUEST)."""

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST
from util import parse_date, is_int, is_num


def body():
    """JSON object body; a missing body behaves as an empty object so that
    required-field checks fire uniformly."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _missing(data, field):
    return field not in data or data[field] is None


def req_str(data, field):
    if _missing(data, field):
        raise_err(ERR_INVALID_REQUEST, "%s is required" % field)
    if not isinstance(data[field], str) or data[field] == "":
        raise_err(ERR_INVALID_REQUEST, "%s must be a non-empty string" % field)
    return data[field]


def opt_str(data, field, default=None):
    if _missing(data, field):
        return default
    if not isinstance(data[field], str):
        raise_err(ERR_INVALID_REQUEST, "%s must be a string" % field)
    return data[field]


def req_int(data, field):
    if _missing(data, field):
        raise_err(ERR_INVALID_REQUEST, "%s is required" % field)
    if not is_int(data[field]):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    return data[field]


def opt_int(data, field, default=None):
    if _missing(data, field):
        return default
    if not is_int(data[field]):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    return data[field]


def req_num(data, field):
    if _missing(data, field):
        raise_err(ERR_INVALID_REQUEST, "%s is required" % field)
    if not is_num(data[field]):
        raise_err(ERR_INVALID_REQUEST, "%s must be a number" % field)
    return data[field]


def opt_num(data, field, default=None):
    if _missing(data, field):
        return default
    if not is_num(data[field]):
        raise_err(ERR_INVALID_REQUEST, "%s must be a number" % field)
    return data[field]


def opt_bool(data, field, default=None):
    if _missing(data, field):
        return default
    if not isinstance(data[field], bool):
        raise_err(ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return data[field]


def req_enum(data, field, values):
    if _missing(data, field):
        raise_err(ERR_INVALID_REQUEST, "%s is required" % field)
    if data[field] not in values:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(values)))
    return data[field]


def opt_enum(data, field, values, default=None):
    if _missing(data, field):
        return default
    if data[field] not in values:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(values)))
    return data[field]


def req_date(data, field):
    """Required ISO date string, shape-checked at stage 2. Returns the raw
    string; business date-sanity rules run later at stage 12."""
    raw = req_str(data, field)
    if parse_date(raw) is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO date (yyyy-mm-dd)" % field)
    return raw


def opt_date(data, field, default=None):
    if _missing(data, field):
        return default
    raw = data[field]
    if not isinstance(raw, str) or parse_date(raw) is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO date (yyyy-mm-dd)" % field)
    return raw


def req_hours(data, field):
    """hours_worked: 0.5..12.0 in 0.5 steps."""
    v = req_num(data, field)
    doubled = v * 2
    if v < 0.5 or v > 12.0 or doubled != int(doubled):
        raise_err(ERR_INVALID_REQUEST, "hours_worked must be between 0.5 and 12.0 in 0.5 steps")
    return v


def req_periods(data, field):
    v = req_int(data, field)
    if v < 1:
        raise_err(ERR_INVALID_REQUEST, "periods must be at least 1")
    return v
