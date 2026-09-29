"""Request-shape validation (band 4 of the precedence ladder, PRD 2.11).

Every failure in this module is ERR_INVALID_REQUEST / 400.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
FEIN_RE = re.compile(r"^[0-9]{2}-[0-9]{7}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
TCN_RE = re.compile(r"^T[0-9]{2}[A-Z]{2}[0-9]{4}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

TWO_PLACES = Decimal("0.01")


def _bad(field):
    raise ApiError("ERR_INVALID_REQUEST",
                   "Field '%s' is missing or invalid." % field)


def body():
    """The JSON request body as a dict; an absent body reads as empty."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, min_len=1, max_len=None):
    if not present(data, field):
        _bad(field)
    value = data[field]
    if not isinstance(value, str):
        _bad(field)
    if len(value) < min_len:
        _bad(field)
    if max_len is not None and len(value) > max_len:
        _bad(field)
    return value


def opt_str(data, field, min_len=1, max_len=None, default=None):
    if not present(data, field):
        return default
    return req_str(data, field, min_len, max_len)


def req_pattern(data, field, regex):
    value = req_str(data, field)
    if not regex.match(value):
        _bad(field)
    return value


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        _bad(field)
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_bool(data, field):
    if not present(data, field):
        _bad(field)
    value = data[field]
    if not isinstance(value, bool):
        _bad(field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        _bad(field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field)
    if minimum is not None and value < minimum:
        _bad(field)
    if maximum is not None and value > maximum:
        _bad(field)
    return value


def _to_decimal(field, value):
    if isinstance(value, bool):
        _bad(field)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            _bad(field)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            _bad(field)
    _bad(field)


def req_gallons(data, field, gt=None, ge=None):
    """A gallons quantity carried to exactly two decimal places."""
    if not present(data, field):
        _bad(field)
    value = _to_decimal(field, data[field])
    if not value.is_finite():
        _bad(field)
    value = value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if gt is not None and value <= gt:
        _bad(field)
    if ge is not None and value < ge:
        _bad(field)
    return value


def opt_gallons(data, field, gt=None, ge=None, default=None):
    if not present(data, field):
        return default
    return req_gallons(data, field, gt, ge)


def req_month(data, field):
    return req_pattern(data, field, MONTH_RE)


def opt_month(data, field, default=None):
    if not present(data, field):
        return default
    return req_month(data, field)


def req_date(data, field):
    value = req_str(data, field)
    if not DATE_RE.match(value):
        _bad(field)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        _bad(field)


def opt_date(data, field, default=None):
    if not present(data, field):
        return default
    return req_date(data, field)


def req_timestamp(data, field):
    value = req_str(data, field)
    parsed = db.parse_timestamp(value)
    if parsed is None:
        _bad(field)
    return parsed


def opt_id(data, field):
    """An optional foreign key: absent or explicit null both read as None."""
    if not present(data, field):
        return None
    value = data[field]
    if not isinstance(value, str) or not value:
        _bad(field)
    return value


def req_id(data, field):
    return req_str(data, field)
