"""Shared request-body validation helpers (priority 4: ERR_INVALID_REQUEST;
priority 13: ERR_INVALID_QTY).

PRD §2.4/§2.5: quantities are integers; money is integer cents; datetimes are
ISO8601 UTC. Validation priority order per SCAFFOLD §1.4: auth(1-2) ->
existence(3) -> body well-formedness(4) -> state(5-6) -> business rules(7+).
"""
from db import _parse_iso
from errors import err_invalid_request, err_invalid_qty


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    return body


def req_string(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise err_invalid_request("missing or invalid field: " + field)
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request("invalid field: " + field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_invalid_request("missing or invalid boolean field: " + field)
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request("missing or invalid integer field: " + field)
    if minimum is not None and v < minimum:
        raise err_invalid_request("field below minimum: " + field)
    return v


def opt_int(body, field, minimum=None, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum)


def req_number(body, field, allow_int=True):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request("missing or invalid numeric field: " + field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request("invalid enum field: " + field)
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err_invalid_request("missing or invalid datetime field: " + field)
    try:
        return _parse_iso(v)
    except Exception:
        raise err_invalid_request("invalid ISO8601 datetime: " + field)


def req_lines_array(body, field="lines", min_len=1):
    v = body.get(field)
    if not isinstance(v, list) or len(v) < min_len:
        raise err_invalid_request("lines must be a non-empty array")
    for el in v:
        if not isinstance(el, dict):
            raise err_invalid_request("each line must be an object")
    return v


def qty_at_least_one(value):
    """ERR_INVALID_QTY when a planned/requested/payment qty is not >= 1."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise err_invalid_qty("quantity must be an integer >= 1")
    return value


def qty_at_least_zero(value):
    """ERR_INVALID_QTY when a confirmed qty is not >= 0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise err_invalid_qty("confirmed quantity must be an integer >= 0")
    return value
