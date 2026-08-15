"""Request-body validation helpers.

PRD §2.8 tier 5 (ERR_INVALID_REQUEST, 400): required fields present, no
unknown fields, valid enums, positive integer cents where required,
well-formed datetimes, uniqueness, and the §2.5 clock-consistency rules.
"""
from db import _parse_iso
from errors import err_invalid_request
from util import parse_date_strict


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    return body


def check_unknown(body, allowed):
    for key in body:
        if key not in allowed:
            raise err_invalid_request("unknown field: " + str(key))


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


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err_invalid_request("invalid boolean field: " + field)
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


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request("missing or invalid numeric field: " + field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request("invalid enum field: " + field)
    return v


def req_date(body, field):
    """Strict YYYY-MM-DD date; returns datetime.date."""
    v = body.get(field)
    d = parse_date_strict(v)
    if d is None:
        raise err_invalid_request("missing or invalid date field (YYYY-MM-DD): " + field)
    return d


def req_datetime(body, field):
    """ISO8601 datetime; returns aware UTC datetime."""
    v = body.get(field)
    if not isinstance(v, str):
        raise err_invalid_request("missing or invalid datetime field: " + field)
    try:
        return _parse_iso(v)
    except Exception:
        raise err_invalid_request("invalid ISO8601 datetime: " + field)


def req_datetime_raw(body, field):
    """ISO8601 datetime; returns (raw string, aware UTC datetime). Input-provided
    datetimes are stored verbatim (tests assert exact string equality, e.g.
    scheduled_sale_start_at == '2026-11-30T10:00:00Z'); all comparisons parse
    the stored string on demand."""
    v = body.get(field)
    if not isinstance(v, str):
        raise err_invalid_request("missing or invalid datetime field: " + field)
    try:
        return v, _parse_iso(v)
    except Exception:
        raise err_invalid_request("invalid ISO8601 datetime: " + field)
