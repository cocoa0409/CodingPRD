"""Validation tier 4: request shape, ranges, enums, datetimes and pagination.

Every failure here is ERR_INVALID_REQUEST (HTTP 400) unless a dedicated
uniqueness code applies, which the route modules raise themselves.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError

MISSING = object()


def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body():
    """The JSON body as a dict. An absent body is treated as an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        _bad()
    if not isinstance(payload, dict):
        _bad()
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if not _present(data, name):
        _bad()
    value = data[name]
    if not isinstance(value, str):
        _bad()
    if len(value) < min_len:
        _bad()
    if max_len is not None and len(value) > max_len:
        _bad()
    return value


def opt_str(data, name, default=None, min_len=1, max_len=None):
    if not _present(data, name):
        return default
    return req_str(data, name, min_len=min_len, max_len=max_len)


def _as_int(value):
    if isinstance(value, bool):
        _bad()
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    _bad()


def req_int(data, name, minimum=None, maximum=None, allowed=None):
    if not _present(data, name):
        _bad()
    value = _as_int(data[name])
    if minimum is not None and value < minimum:
        _bad()
    if maximum is not None and value > maximum:
        _bad()
    if allowed is not None and value not in allowed:
        _bad()
    return value


def opt_int(data, name, default, minimum=None, maximum=None, allowed=None):
    if not _present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum, allowed=allowed)


def req_bool(data, name):
    if not _present(data, name):
        _bad()
    value = data[name]
    if not isinstance(value, bool):
        _bad()
    return value


def opt_bool(data, name, default):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        _bad()
    return value


def req_decimal(data, name, gt=None, lte=None):
    if not _present(data, name):
        _bad()
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _bad()
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad()
    if gt is not None and not number > Decimal(str(gt)):
        _bad()
    if lte is not None and not number <= Decimal(str(lte)):
        _bad()
    return number


def req_dt(data, name):
    if not _present(data, name):
        _bad()
    value = data[name]
    if not isinstance(value, str):
        _bad()
    parsed = store.parse_iso(value)
    if parsed is None:
        _bad()
    return parsed


def opt_ref(data, name):
    """An optional foreign key: absent or null means None; anything else must be a string."""
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str) or value == "":
        _bad()
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad()
        if limit < 1 or limit > 100:
            _bad()
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad()
        if offset < 0:
            _bad()
    return limit, offset


def filter_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filter_bool(name):
    """A boolean query filter. Anything that is not a boolean literal is malformed."""
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad()


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        _bad()
    return value
