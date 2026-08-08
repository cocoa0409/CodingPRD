"""Validation ladder rungs 4, 5 and the shared list-query screening.

Rung 4  request schema  priority  9 required-present + declared JSON type -> ERR_VALIDATION
                        priority 10 enum membership                       -> ERR_INVALID_ENUM
                        priority 11 numeric ranges                        -> ERR_VALIDATION
Rung 5  dates           priority 12 parse                                 -> ERR_VALIDATION
                        priority 13 ordering / window                     -> ERR_INVALID_DATE_RANGE

ENUM ROUTING RULE (single, uniform): a field whose declared JSON type is a
string enum is first type-checked at priority 9; once it is a string, ANY value
outside the declared member set — in a request body or in a list filter, whether
or not the PRD names that particular field in its illustrative list — is
ERR_INVALID_ENUM (400).  No enum field is left on the generic ERR_VALIDATION.
"""
from flask import request

import constants as C
from errors import ApiError
from timeutil import normalize_datetime, parse_date, parse_datetime


def json_body():
    """Absent or malformed JSON is treated as an empty object; endpoints that
    declare required fields then fail priority 9 with ERR_VALIDATION."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


# ------------------------------------------------- priority 9: shape -------
def req_string(body, name):
    value = body.get(name)
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a non-empty string." % name)
    return value


def opt_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a non-empty string." % name)
    return value


def req_int(body, name):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an integer." % name)
    return value


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an integer." % name)
    return value


def req_number(body, name):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a number." % name)
    return value


def req_bool(body, name):
    value = body.get(name)
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
    return value


def req_string_array(body, name):
    value = body.get(name)
    if not isinstance(value, list) or len(value) == 0:
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must contain strings." % name)
    return value


# ---------------------------------------------- priority 10: enum member ----
def enum_member(value, allowed, name):
    if value is None:
        return None
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "Field '%s' carries a value outside its declared member set." % name,
        )
    return value


def req_enum(body, name, allowed):
    """Type first (priority 9), membership second (priority 10)."""
    value = req_string(body, name)
    return enum_member(value, allowed, name)


def opt_enum(body, name, allowed, default=None):
    value = opt_string(body, name, None)
    if value is None:
        return default
    return enum_member(value, allowed, name)


# ------------------------------------------------ priority 11: ranges -------
def check_range(condition, message):
    if not condition:
        raise ApiError("ERR_VALIDATION", message)


# ------------------------------------------------ priority 12: date parse ---
def req_date(body, name):
    raw = req_string(body, name)
    value = parse_date(raw)
    if value is None:
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % name)
    return value


def req_datetime(body, name):
    raw = req_string(body, name)
    value = parse_datetime(raw)
    if value is None:
        raise ApiError(
            "ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC datetime." % name
        )
    # Inbound datetimes are normalised to the millisecond resolution the API
    # emits, so an echoed value round-trips byte-identically to a server stamp.
    return normalize_datetime(value)


def date_range(condition, message):
    if not condition:
        raise ApiError("ERR_INVALID_DATE_RANGE", message)


# ------------------------------------------------------ list query screen ---
def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)


def pagination():
    """priority 11 — limit between 1 and 100, offset at least 0."""
    limit = _query_int("limit", C.PAGE_LIMIT_DEFAULT)
    offset = _query_int("offset", C.PAGE_OFFSET_DEFAULT)
    if limit < C.PAGE_LIMIT_MIN or limit > C.PAGE_LIMIT_MAX:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset may not be negative.")
    return limit, offset


def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def enum_filter(name, allowed):
    """priority 10 — every enum-typed list filter routes to ERR_INVALID_ENUM."""
    raw = filter_value(name)
    if raw is None:
        return None
    return enum_member(raw, allowed, name)
