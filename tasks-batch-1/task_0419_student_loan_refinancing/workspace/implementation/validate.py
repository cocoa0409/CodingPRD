"""Request body / query-param validation helpers.

Malformed bodies — missing required field, wrong type, bad enum, non-positive
amount where positive required — yield ERR_INVALID_REQUEST (400) per PRD §2.6.
Pagination out of range yields ERR_PAGINATION_INVALID (400) per PRD §2.3.
"""
from flask import request

from errors import err


def get_json_body():
    """Parse the JSON body; tolerate an empty body as {}.

    A body that is present but malformed (not a JSON object) is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
    return data


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "missing or empty field: %s" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % field)
    return v


def require_positive_int(body, field):
    v = require_int(body, field)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", "field %s must be > 0" % field)
    return v


def require_nonneg_int(body, field):
    v = require_int(body, field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "field %s must be >= 0" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "field %s must be one of %s" % (field, sorted(allowed)))
    return v


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "field %s must be a boolean" % field)
    return v


def parse_pagination():
    """Return (limit, offset). limit default 10 (1..100), offset default 0 (>=0).

    Out of range or non-integer -> ERR_PAGINATION_INVALID (PRD §2.3).
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit out of range")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")

    return limit, offset
