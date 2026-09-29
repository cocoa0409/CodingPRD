"""Priority 6 -- body well-formedness helpers.  Every violation raises
ERR_INVALID_REQUEST (422) per PRD section 2.8.
"""

from decimal import Decimal, InvalidOperation

import db
from errors import fail

MISSING = object()


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s." % (field, why))


def present(payload, field):
    return field in payload and payload[field] is not None


def req_string(payload, field, min_len=1, max_len=None, default=MISSING):
    if not present(payload, field):
        if default is not MISSING:
            return default
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if min_len is not None and min_len >= 1 and not value.strip():
        _bad(field, "must be a non-blank string")
    if min_len is not None and len(value) < min_len:
        _bad(field, "is shorter than %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "is longer than %d characters" % max_len)
    return value


def opt_string(payload, field, min_len=None, max_len=None, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if min_len is not None and len(value.strip()) < min_len:
        _bad(field, "must be a non-blank string")
    if max_len is not None and len(value) > max_len:
        _bad(field, "is longer than %d characters" % max_len)
    return value


def req_enum(payload, field, allowed, default=MISSING):
    if not present(payload, field):
        if default is not MISSING:
            return default
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not present(payload, field):
        return default
    return req_enum(payload, field, allowed)


def req_int(payload, field, minimum=None, maximum=None, default=MISSING):
    if not present(payload, field):
        if default is not MISSING:
            return default
        _bad(field, "is required")
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must not exceed %s" % maximum)
    return value


def req_decimal(payload, field, minimum=None, maximum=None, default=MISSING,
                exclusive_min=False, exclusive_max=False):
    if not present(payload, field):
        if default is not MISSING:
            return default if default is None else Decimal(str(default))
        _bad(field, "is required")
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field, "must be a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if not number.is_finite():
        _bad(field, "must be a finite number")
    if minimum is not None:
        floor = Decimal(str(minimum))
        if exclusive_min and number <= floor:
            _bad(field, "must be greater than %s" % minimum)
        if not exclusive_min and number < floor:
            _bad(field, "must be at least %s" % minimum)
    if maximum is not None:
        ceiling = Decimal(str(maximum))
        if exclusive_max and number >= ceiling:
            _bad(field, "must be less than %s" % maximum)
        if not exclusive_max and number > ceiling:
            _bad(field, "must not exceed %s" % maximum)
    return number


def req_datetime(payload, field, default=MISSING):
    if not present(payload, field):
        if default is not MISSING:
            return default
        _bad(field, "is required")
    parsed = db.parse_dt(payload[field])
    if parsed is None:
        _bad(field, "must be an ISO 8601 timestamp")
    return parsed


def req_str_list(payload, field, min_items=0, max_items=None, allowed=None,
                 distinct=False, default=MISSING):
    if not present(payload, field):
        if default is not MISSING:
            return default
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if min_items is not None and len(value) < min_items:
        _bad(field, "must hold at least %d entries" % min_items)
    if max_items is not None and len(value) > max_items:
        _bad(field, "must hold at most %d entries" % max_items)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad(field, "must hold non-blank strings")
        if allowed is not None and item not in allowed:
            _bad(field, "holds an unknown value %r" % item)
    if distinct and len(set(value)) != len(value):
        _bad(field, "must not repeat a value")
    return value
