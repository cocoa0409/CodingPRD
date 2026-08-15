from db import STORE, is_int, parse_ts, parse_hhmm, norm_hhmm
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND)


def get_or_404(store_key, rid, label="Resource"):
    ent = STORE[store_key].get(rid)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found: %s" % (label, rid))
    return ent


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid required field: %s" % field)
    return v


def opt_str(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Invalid field (must be string): %s" % field)
    return v


def req_enum(b, field, values):
    v = b.get(field)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid value for %s" % field)
    return v


def req_int(b, field):
    v = b.get(field)
    if not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid integer field: %s" % field)
    return v


def opt_int(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Invalid integer field: %s" % field)
    return v


def opt_ts(b, field):
    """Optional datetime field; present-but-unparseable -> 400."""
    v = b.get(field)
    if v is None:
        return None
    dt = parse_ts(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Invalid timestamp for %s" % field)
    return dt


def req_ts(b, field):
    v = b.get(field)
    dt = parse_ts(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid timestamp for %s" % field)
    return dt


def opt_hhmm(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    n = norm_hhmm(v)
    if n is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Invalid HH:MM value for %s" % field)
    return n


def req_hhmm(b, field):
    v = b.get(field)
    n = norm_hhmm(v)
    if n is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid HH:MM value for %s" % field)
    return n


def opt_str_list(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if (not isinstance(v, list)
            or any(not isinstance(x, str) for x in v)):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Invalid array of strings for %s" % field)
    return list(v)
