"""Request body shape validation (ERR_INVALID_REQUEST, HTTP 400)."""

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST
from util import is_int, is_num, parse_datetime, parse_quarter


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


def req_positive_num(data, field):
    v = req_num(data, field)
    if v <= 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be greater than zero" % field)
    return v


def req_nonneg_num(data, field):
    v = req_num(data, field)
    if v < 0:
        raise_err(ERR_INVALID_REQUEST, "%s must be at least zero" % field)
    return v


def req_datetime(data, field):
    raw = req_str(data, field)
    dt = parse_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime" % field)
    return dt


def req_quarter(data, field):
    raw = req_str(data, field)
    if parse_quarter(raw) is None:
        raise_err(ERR_INVALID_REQUEST, "%s must be a YYYY-Qn quarter label" % field)
    return raw
