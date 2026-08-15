"""Stage-2 request-shape validation helpers and pagination parsing."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import raise_error
from util import parse_dt

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error("ERR_INVALID_REQUEST", f"invalid field type: {field}")
    return v


def req_int(body, field, positive=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error("ERR_INVALID_REQUEST", f"field {field} must be > 0")
    return v


def opt_int(body, field, default=None, positive=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, positive=positive)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_error("ERR_INVALID_REQUEST", f"invalid boolean field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid enum field: {field}")
    return v


def req_date(body, field):
    v = req_str(body, field)
    try:
        date.fromisoformat(v)
    except (ValueError, TypeError):
        raise_error("ERR_INVALID_REQUEST", f"invalid ISO date: {field}")
    if len(v) != 10:
        raise_error("ERR_INVALID_REQUEST", f"invalid ISO date: {field}")
    return v


def opt_nullable_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def req_period(body, field):
    v = req_str(body, field)
    if not _PERIOD_RE.match(v):
        raise_error("ERR_INVALID_REQUEST", f"invalid period (YYYY-MM): {field}")
    return v


def req_datetime_iso(body, field):
    v = req_str(body, field)
    try:
        parse_dt(v)
    except (ValueError, TypeError):
        raise_error("ERR_INVALID_REQUEST", f"invalid ISO 8601 datetime: {field}")
    return v


def opt_weight_lbs(body, field="weight_lbs"):
    """A provided weight_lbs must be positive with at most one decimal place."""
    if field not in body or body.get(field) is None:
        return None
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error("ERR_INVALID_REQUEST", f"invalid weight: {field}")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise_error("ERR_INVALID_REQUEST", f"invalid weight: {field}")
    if d <= 0:
        raise_error("ERR_INVALID_REQUEST", f"field {field} must be > 0")
    if -d.as_tuple().exponent > 1:
        raise_error("ERR_INVALID_REQUEST", f"field {field} allows at most 1 decimal place")
    return d


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
