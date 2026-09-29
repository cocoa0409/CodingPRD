"""Payload / query-string schema validation (ladder rung 4)."""
from decimal import Decimal, InvalidOperation

from flask import request

from db import D, rhu
from errors import ApiError

_MISSING = object()


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def get_body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad()
    if not isinstance(payload, dict):
        bad()
    return payload


# --------------------------------------------------------------------------
# body field readers
# --------------------------------------------------------------------------

def field_str(body, key, required=True, min_len=1, max_len=None, default=None):
    if key not in body or body[key] is None:
        if required:
            bad()
        return default
    value = body[key]
    if not isinstance(value, str):
        bad()
    if min_len is not None and len(value) < min_len:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def field_int(body, key, required=True, low=None, high=None, default=None):
    if key not in body or body[key] is None:
        if required:
            bad()
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    if low is not None and value < low:
        bad()
    if high is not None and value > high:
        bad()
    return value


def field_decimal(body, key, places, required=True, low=None, high=None, default=None):
    if key not in body or body[key] is None:
        if required:
            bad()
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad()
    try:
        value = D(str(value))
    except (InvalidOperation, ValueError):
        bad()
    if not value.is_finite():
        bad()
    if low is not None and value < D(str(low)):
        bad()
    if high is not None and value > D(str(high)):
        bad()
    return rhu(value, places)


def field_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            bad()
        return default
    value = body[key]
    if not isinstance(value, bool):
        bad()
    return value


def field_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            bad()
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad()
    return value


def field_date(body, key, required=True, default=None):
    """ISO calendar date (YYYY-MM-DD), returned as its canonical string."""
    if key not in body or body[key] is None:
        if required:
            bad()
        return default
    value = body[key]
    if not isinstance(value, str):
        bad()
    return _parse_date_string(value)


def _parse_date_string(value):
    import datetime as _dt

    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        bad()
    try:
        parsed = _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        bad()
    return parsed.isoformat()


def parse_instant(value):
    import datetime as _dt

    if not isinstance(value, str) or not value:
        bad()
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        bad()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


# --------------------------------------------------------------------------
# query string readers
# --------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    if "limit" in request.args:
        limit = _query_int(request.args["limit"])
        if limit < 1 or limit > 100:
            bad()
    if "offset" in request.args:
        offset = _query_int(request.args["offset"])
        if offset < 0:
            bad()
    return limit, offset


def _query_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        bad()


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad()
    return value


def query_str(name):
    return request.args.get(name)


def query_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    return _query_int(value)


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    bad()
