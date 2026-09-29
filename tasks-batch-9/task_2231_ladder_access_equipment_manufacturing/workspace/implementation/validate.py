"""Request body / query validation helpers.

Every failure here raises the exact error_id the PRD ladder (2.5) assigns to the
check, so route code can express the ladder as a straight-line sequence.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError

MISSING = object()


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def present(data, name):
    return name in data and data[name] is not None


# --------------------------------------------------------------------------
# scalar field validators (ERR_INVALID_REQUEST, ladder step 6)
# --------------------------------------------------------------------------
def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "field '%s' %s" % (name, why))


def req_str(data, name, max_length=None, min_length=1):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_length is not None and len(value) < min_length:
        _bad(name, "must be at least %d characters" % min_length)
    if max_length is not None and len(value) > max_length:
        _bad(name, "must be at most %d characters" % max_length)
    return value


def opt_str(data, name, max_length=None, min_length=1, default=None):
    if not present(data, name):
        return default
    return req_str(data, name, max_length=max_length, min_length=min_length)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def _to_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")


def req_number(data, name, minimum=None, maximum=None, exclusive_min=False):
    if not present(data, name):
        _bad(name, "is required")
    number = _to_decimal(name, data[name])
    _check_number_bounds(name, number, minimum, maximum, exclusive_min)
    return number


def opt_number(data, name, minimum=None, maximum=None, exclusive_min=False, default=None):
    if not present(data, name):
        return default
    return req_number(data, name, minimum, maximum, exclusive_min)


def _check_number_bounds(name, number, minimum, maximum, exclusive_min):
    if minimum is not None:
        if exclusive_min and number <= Decimal(str(minimum)):
            _bad(name, "must be greater than %s" % minimum)
        if not exclusive_min and number < Decimal(str(minimum)):
            _bad(name, "must be at least %s" % minimum)
    if maximum is not None and number > Decimal(str(maximum)):
        _bad(name, "must be at most %s" % maximum)


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return req_int(data, name, minimum, maximum)


def req_bool(data, name, default=None):
    if not present(data, name):
        if default is None:
            _bad(name, "is required")
        return default
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(data, name):
    if not present(data, name):
        _bad(name, "is required")
    parsed = parse_instant(data[name])
    if parsed is None:
        _bad(name, "must be an ISO 8601 datetime")
    return parsed


def opt_instant(data, name, default=None):
    if not present(data, name):
        return default
    return req_instant(data, name)


def req_id(data, name):
    return req_str(data, name)


def opt_id(data, name):
    if not present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str) or not value:
        _bad(name, "must be a string identifier")
    return value


def req_str_array(data, name, allowed=None):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, list) or not value:
        _bad(name, "must be a non-empty array")
    for member in value:
        if not isinstance(member, str) or not member:
            _bad(name, "members must be non-empty strings")
        if allowed is not None and member not in allowed:
            _bad(name, "members must be drawn from %s" % ", ".join(allowed))
    return value


# --------------------------------------------------------------------------
# temporal helpers
# --------------------------------------------------------------------------
def check_window(start, end):
    """Ladder step 8: ERR_INVALID_WINDOW when both bounds are supplied."""
    if start is not None and end is not None and not start < end:
        raise ApiError("ERR_INVALID_WINDOW", "window start must precede window end")


def check_not_future(instant, field):
    """Ladder step 9: ERR_DATE_IN_FUTURE."""
    if instant is not None and instant > store.now():
        raise ApiError(
            "ERR_DATE_IN_FUTURE", "%s must not be later than the current instant" % field
        )


# --------------------------------------------------------------------------
# pagination and filters
# --------------------------------------------------------------------------
def _query_int(name):
    raw_value = request.args.get(name)
    if raw_value is None or raw_value == "":
        return None
    text = raw_value.strip()
    negative = text.startswith("-")
    digits = text[1:] if (negative or text.startswith("+")) else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    value = int(text)
    return value


def pagination():
    """Ladder step 7: limit in 1..100 (default 10), offset >= 0 (default 0)."""
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = 10
    elif limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be non-negative")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def matches_filters(row, spec):
    """spec maps query-parameter name -> stored field name."""
    for param, field in spec.items():
        wanted = filter_value(param)
        if wanted is None:
            continue
        actual = row.get(field)
        if isinstance(actual, bool):
            lowered = wanted.strip().lower()
            if lowered in ("true", "1"):
                if actual is not True:
                    return False
            elif lowered in ("false", "0"):
                if actual is not False:
                    return False
            else:
                return False
        elif actual is None:
            return False
        elif str(actual) != wanted:
            return False
    return True


def sorted_rows(rows):
    """PRD 2.3: list endpoints sort by created_at ascending (stable)."""
    return sorted(rows, key=lambda row: row["created_at"])
