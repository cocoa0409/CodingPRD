"""Pipeline stage 4: request body shape validation (ERR_INVALID_REQUEST)."""

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST
from util import parse_datetime, is_int, is_num


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


def req_pos_int(data, field):
    v = req_int(data, field)
    if v <= 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be greater than 0" % field)
    return v


def opt_pos_int(data, field, default=None):
    v = opt_int(data, field, default)
    if v is not None and v <= 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be greater than 0" % field)
    return v


def req_nonneg_int(data, field):
    v = req_int(data, field)
    if v < 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be at least 0" % field)
    return v


def opt_nonneg_int(data, field, default=None):
    v = opt_int(data, field, default)
    if v is not None and v < 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be at least 0" % field)
    return v


def req_num(data, field):
    if _missing(data, field):
        raise_err(ERR_INVALID_REQUEST, "%s is required" % field)
    if not is_num(data[field]):
        raise_err(ERR_INVALID_REQUEST, "%s must be a number" % field)
    return data[field]


def req_pos_num(data, field):
    v = req_num(data, field)
    if v <= 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be greater than 0" % field)
    return v


def req_bool(data, field):
    if _missing(data, field):
        raise_err(ERR_INVALID_REQUEST, "%s is required" % field)
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


def req_datetime(data, field):
    """Required ISO 8601 datetime string. Returns an aware UTC datetime."""
    raw = req_str(data, field)
    dt = parse_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime" % field)
    return dt
