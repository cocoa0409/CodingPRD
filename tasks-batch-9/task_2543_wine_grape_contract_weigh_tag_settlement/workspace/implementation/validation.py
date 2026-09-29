"""Rank-7 request-shape validation and rank-8 pagination bounds."""
from decimal import Decimal

from flask import request

from common import D, fail, parse_dt

_MISSING = object()


def dec_places(value):
    """Number of significant decimal places of a Decimal literal."""
    d = D(value).normalize()
    sign, digits, exponent = d.as_tuple()
    if not isinstance(exponent, int):
        return 0
    return -exponent if exponent < 0 else 0


def present(body, name):
    return name in body and body[name] is not None


def bad(name, why):
    fail("ERR_VALIDATION", "Field '%s' %s." % (name, why))


def no_unknown_keys(body, allowed):
    for key in body.keys():
        if key not in allowed:
            fail("ERR_VALIDATION", "Unknown field '%s'." % key)


def req_str(body, name, min_len=1, max_len=None, charset=None):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return opt_str(body, name, min_len, max_len, charset)


def opt_str(body, name, min_len=1, max_len=None, charset=None, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if value.strip() == "" and min_len > 0:
        bad(name, "may not be blank")
    if len(value) < min_len:
        bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(name, "must be at most %d characters" % max_len)
    if charset is not None:
        for ch in value:
            if ch not in charset:
                bad(name, "contains a character outside its permitted set")
    return value


def free_text(body, name):
    """An optional free-text field the server does not interpret."""
    if name not in body or body[name] is None:
        return None
    if not isinstance(body[name], str):
        bad(name, "must be a string")
    return body[name]


def req_enum(body, name, choices):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return opt_enum(body, name, choices)


def opt_enum(body, name, choices, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if value not in choices:
        bad(name, "must be one of %s" % ", ".join(choices))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return opt_int(body, name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not _is_int(value):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be at most %s" % maximum)
    return value


def req_num(body, name, places, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return opt_num(body, name, places, minimum, maximum, exclusive_min, exclusive_max)


def opt_num(body, name, places, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad(name, "must be a number")
    num = D(value)
    if dec_places(num) > places:
        bad(name, "may carry at most %d decimal place(s)" % places)
    if exclusive_min is not None and not num > D(exclusive_min):
        bad(name, "must be greater than %s" % exclusive_min)
    if minimum is not None and num < D(minimum):
        bad(name, "must be at least %s" % minimum)
    if exclusive_max is not None and not num < D(exclusive_max):
        bad(name, "must be less than %s" % exclusive_max)
    if maximum is not None and num > D(maximum):
        bad(name, "must be at most %s" % maximum)
    return num


def req_bool(body, name):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return opt_bool(body, name)


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        bad(name, "must be a boolean")
    return body[name]


def req_dt(body, name):
    if name not in body or body[name] is None:
        bad(name, "is required")
    return opt_dt(body, name)


def opt_dt(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        bad(name, "must be an ISO 8601 string")
    parsed = parse_dt(body[name])
    if parsed is None:
        bad(name, "must be a parseable ISO 8601 instant")
    return parsed


def req_id(body, name):
    """A foreign-key field: must be present and a string, else rank-7."""
    if name not in body or body[name] is None:
        bad(name, "is required")
    if not isinstance(body[name], str) or body[name].strip() == "":
        bad(name, "must be a non-empty string")
    return body[name]


def window(start, end):
    """Rank-7: any window's window_end must be strictly after its window_start."""
    if start is not None and end is not None and not end > start:
        fail("ERR_VALIDATION", "Field 'window_end' must be strictly after 'window_start'.")


# --------------------------------------------------------------------------
# rank 8 -- pagination
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "Query parameter 'limit' must be an integer.")
        if str(raw_limit).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "Query parameter 'offset' must be an integer.")
        if str(raw_offset).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "Query parameter 'offset' may not be negative.")
    return limit, offset


def filt(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filt_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    return None


def page(items, limit, offset):
    return items[offset:offset + limit]
