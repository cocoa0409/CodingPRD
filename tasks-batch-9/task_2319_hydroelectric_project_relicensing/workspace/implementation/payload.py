"""Request payload parsing / field validation helpers.

Body-shape violations raise ERR_INVALID_REQUEST (400); pagination violations
raise ERR_VALIDATION (400), per PRD 2.3 and PRD 2.12 rules 7-10.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError

_MISSING = object()


def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def present(data, name):
    return name in data and data[name] is not None


def bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def req_field(data, name):
    if name not in data or data[name] is None:
        bad(name, "is required")
    return data[name]


def req_string(data, name, allow_empty=False):
    value = req_field(data, name)
    if not isinstance(value, str):
        bad(name, "must be a string")
    if not allow_empty and not value.strip():
        bad(name, "must be non-empty")
    return value


def opt_string(data, name, default=None, allow_empty=True):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if not allow_empty and not value.strip():
        bad(name, "must be non-empty")
    return value


def req_enum(data, name, allowed):
    value = req_field(data, name)
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def _as_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad(name, "must be a number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad(name, "must be a number")


def req_number(data, name, minimum=None, maximum=None, exclusive_min=None):
    value = _as_decimal(name, req_field(data, name))
    _check_range(name, value, minimum, maximum, exclusive_min)
    return value


def opt_number(data, name, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not present(data, name):
        return default
    value = _as_decimal(name, data[name])
    _check_range(name, value, minimum, maximum, exclusive_min)
    return value


def _check_range(name, value, minimum, maximum, exclusive_min):
    if minimum is not None and value < Decimal(str(minimum)):
        bad(name, "must be >= %s" % minimum)
    if exclusive_min is not None and value <= Decimal(str(exclusive_min)):
        bad(name, "must be > %s" % exclusive_min)
    if maximum is not None and value > Decimal(str(maximum)):
        bad(name, "must be <= %s" % maximum)


def _as_int(name, value):
    if isinstance(value, bool):
        bad(name, "must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    bad(name, "must be an integer")


def req_int(data, name, minimum=None, maximum=None):
    value = _as_int(name, req_field(data, name))
    _check_range(name, Decimal(value), minimum, maximum, None)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = _as_int(name, data[name])
    _check_range(name, Decimal(value), minimum, maximum, None)
    return value


def req_bool(data, name):
    value = req_field(data, name)
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    return req_bool(data, name)


def req_date(data, name):
    value = req_field(data, name)
    parsed = clock.parse_iso_date(value) if isinstance(value, str) else None
    if parsed is None:
        bad(name, "must be an ISO 8601 date (YYYY-MM-DD)")
    return parsed


def opt_date(data, name, default=None):
    if not present(data, name):
        return default
    return req_date(data, name)


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be a non-negative integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = query_filter(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return _MISSING


def query_int(name):
    value = query_filter(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return _MISSING


NO_MATCH = _MISSING
