"""Request body shape / range validators (ladder groups 3 and 4)."""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_instant

_MISSING = object()

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    """The JSON request body as a dict; a missing body counts as empty."""
    try:
        payload = request.get_json(silent=True, force=True)
    except Exception:
        payload = None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("request body must be a JSON object")
    return payload


def present(b, name):
    return name in b and b[name] is not None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def req_str(b, name, min_len=1, max_len=None, pattern=None):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_str(b, name, min_len=min_len, max_len=max_len, pattern=pattern)


def opt_str(b, name, min_len=1, max_len=None, pattern=None, default=_MISSING):
    if name not in b or b[name] is None:
        return None if default is _MISSING else default
    value = b[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("%s has an invalid format" % name)
    return value


def req_int(b, name, minimum=None, maximum=None):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_int(b, name, minimum=minimum, maximum=maximum)


def opt_int(b, name, minimum=None, maximum=None, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not _is_int(value):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def req_decimal(b, name, minimum=None, maximum=None, places=None):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_decimal(b, name, minimum=minimum, maximum=maximum, places=places)


def opt_decimal(b, name, minimum=None, maximum=None, places=None, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not _is_num(value):
        bad("%s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("%s must be <= %s" % (name, maximum))
    if places is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -places:
            bad("%s must have at most %d decimal places" % (name, places))
    return dec


def req_bool(b, name):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_bool(b, name)


def opt_bool(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def req_enum(b, name, choices):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_enum(b, name, choices)


def opt_enum(b, name, choices, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, str) or value not in choices:
        bad("%s must be one of %s" % (name, ", ".join(choices)))
    return value


def req_enum_list(b, name, choices, allow_empty=True):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_enum_list(b, name, choices, allow_empty=allow_empty)


def opt_enum_list(b, name, choices, allow_empty=True, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if not allow_empty and len(value) == 0:
        bad("%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or item not in choices:
            bad("%s entries must be one of %s" % (name, ", ".join(choices)))
    return value


def req_str_list(b, name, allow_empty=True, max_len=None):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_str_list(b, name, allow_empty=allow_empty, max_len=max_len)


def opt_str_list(b, name, allow_empty=True, max_len=None, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if not allow_empty and len(value) == 0:
        bad("%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or item == "":
            bad("%s entries must be non-empty strings" % name)
        if max_len is not None and len(item) > max_len:
            bad("%s entries must be at most %d characters" % (name, max_len))
    return value


def req_int_list(b, name, minimum=None, maximum=None, allow_empty=True):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_int_list(b, name, minimum=minimum, maximum=maximum, allow_empty=allow_empty)


def opt_int_list(b, name, minimum=None, maximum=None, allow_empty=True, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if not allow_empty and len(value) == 0:
        bad("%s must not be empty" % name)
    for item in value:
        if not _is_int(item):
            bad("%s entries must be integers" % name)
        if minimum is not None and item < minimum:
            bad("%s entries must be >= %s" % (name, minimum))
        if maximum is not None and item > maximum:
            bad("%s entries must be <= %s" % (name, maximum))
    return value


def req_date(b, name):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_date(b, name)


def opt_date(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, str) or not DATE_RE.match(value):
        bad("%s must be a YYYY-MM-DD date" % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        bad("%s must be a valid calendar date" % name)


def req_instant(b, name):
    if name not in b or b[name] is None:
        bad("%s is required" % name)
    return opt_instant(b, name)


def opt_instant(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 timestamp" % name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be an ISO 8601 timestamp" % name)
    return parsed


def d(value):
    """Parse a stored YYYY-MM-DD string into a date (None-safe)."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def ds(value):
    """Render a date as YYYY-MM-DD (None-safe)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def plus_days(day, count):
    return day + timedelta(days=count)


def fk(b, name, collection, error_id, required=False):
    """Existence check for a body foreign key (ladder group 2).

    A wrong-typed or missing value is left for the shape stage; only a
    well-formed id that does not resolve produces the not-found error.
    """
    if name not in b or b[name] is None:
        if required:
            return None
        return None
    value = b[name]
    if not isinstance(value, str):
        return None
    row = collection.get(value)
    if row is None:
        raise ApiError(error_id, "%s does not identify an existing record" % name)
    return row


def path_row(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "no such record: %s" % row_id)
    return row


def occ(b, name, row, required=True):
    """Optimistic concurrency guard (ladder group 4).

    The guard field is declared required: omitting it is ERR_VALIDATION, not a
    silent skip.  It is evaluated after existence and shape checks and before
    every domain rule.
    """
    if name not in b or b[name] is None:
        if required:
            bad("%s is required" % name)
        return
    expected = b[name]
    if not _is_int(expected):
        bad("%s must be an integer" % name)
    if expected != row["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "%s %d does not match the current version %d"
                       % (name, expected, row["version"]))
