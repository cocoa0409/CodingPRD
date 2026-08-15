"""Shared request-shape validation helpers (priority 4 / 5 utilities)."""

from flask import request

from db import parse_iso
from errors import err400, err404, ERR_INVALID_REQUEST


def body():
    """JSON body as dict; malformed -> ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err400(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err400(ERR_INVALID_REQUEST, "%s is required and must be a string" % field)
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err400(ERR_INVALID_REQUEST, "%s must be a string" % field)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err400(ERR_INVALID_REQUEST, "%s is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err400(ERR_INVALID_REQUEST, "%s must be >= %d" % (field, minimum))
    return v


def opt_int(data, field, default=None, minimum=None):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise err400(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err400(ERR_INVALID_REQUEST, "%s must be >= %d" % (field, minimum))
    return v


def req_enum(data, field, domain):
    v = data.get(field)
    if v not in domain:
        raise err400(ERR_INVALID_REQUEST,
                     "%s must be one of %s" % (field, ", ".join(domain)))
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err400(ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return v


def req_datetime(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise err400(ERR_INVALID_REQUEST, "%s is required and must be an ISO8601 string" % field)
    try:
        parse_iso(v)
    except Exception:
        raise err400(ERR_INVALID_REQUEST, "%s must be a valid ISO8601 datetime" % field)
    return v


def opt_datetime(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err400(ERR_INVALID_REQUEST, "%s must be an ISO8601 string" % field)
    try:
        parse_iso(v)
    except Exception:
        raise err400(ERR_INVALID_REQUEST, "%s must be a valid ISO8601 datetime" % field)
    return v


def get_or_404(table, entity_id, label):
    obj = table.get(entity_id)
    if obj is None:
        raise err404("%s %s not found" % (label, entity_id))
    return obj
