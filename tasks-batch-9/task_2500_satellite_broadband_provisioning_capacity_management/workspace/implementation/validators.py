"""Request-shape validation (PRD 2.11 priority 4).

Every failure in this module is `ERR_INVALID_REQUEST` (HTTP 400).  Nothing here
looks at stored state; foreign keys, version tokens and state preconditions are
checked later, in their own priority bands.
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from clock import parse_iso
from errors import fail

_MISSING = object()

JURISDICTION_FORMAT = re.compile(r"^[A-Z]+(-[A-Z]+)?$")


def body_dict():
    """The parsed JSON body, or an empty mapping when none was supplied."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(body, name):
    return name in body and body[name] is not None


# ---------------------------------------------------------------- strings ----

def req_str(body, name, min_len=1, max_len=200):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    return _check_str(body[name], name, min_len, max_len)


def opt_str(body, name, min_len=1, max_len=200, default=None):
    if not _present(body, name):
        return default
    return _check_str(body[name], name, min_len, max_len)


def _check_str(value, name, min_len, max_len):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "'%s' must be a string." % name)
    if len(value) < min_len or len(value) > max_len:
        fail(
            "ERR_INVALID_REQUEST",
            "'%s' must be between %d and %d characters." % (name, min_len, max_len),
        )
    return value


def req_jurisdiction(body, name, strict_format=False):
    value = req_str(body, name, 2, 8)
    if strict_format and not JURISDICTION_FORMAT.match(value):
        fail(
            "ERR_INVALID_REQUEST",
            "'%s' must be uppercase letters with at most a single hyphen." % name,
        )
    return value


def req_email(body, name="email"):
    value = req_str(body, name, 1, 200)
    if "@" not in value:
        fail("ERR_INVALID_REQUEST", "'%s' must contain an at-sign." % name)
    return value


# ----------------------------------------------------------------- enums -----

def req_enum(body, name, allowed):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    return _check_enum(body[name], name, allowed)


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return _check_enum(body[name], name, allowed)


def _check_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "'%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return value


# --------------------------------------------------------------- numbers -----

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    return _check_int(body[name], name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return _check_int(body[name], name, minimum, maximum)


def _check_int(value, name, minimum, maximum):
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "'%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "'%s' must be at most %s." % (name, maximum))
    return value


def req_num(body, name, gt=None, ge=None, le=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    return _check_num(body[name], name, gt, ge, le)


def opt_num(body, name, gt=None, ge=None, le=None, default=None):
    if not _present(body, name):
        return default
    return _check_num(body[name], name, gt, ge, le)


def _check_num(value, name, gt, ge, le):
    if not _is_num(value):
        fail("ERR_INVALID_REQUEST", "'%s' must be a number." % name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "'%s' must be a number." % name)
    if not number.is_finite():
        fail("ERR_INVALID_REQUEST", "'%s' must be a finite number." % name)
    if gt is not None and number <= Decimal(str(gt)):
        fail("ERR_INVALID_REQUEST", "'%s' must be greater than %s." % (name, gt))
    if ge is not None and number < Decimal(str(ge)):
        fail("ERR_INVALID_REQUEST", "'%s' must be at least %s." % (name, ge))
    if le is not None and number > Decimal(str(le)):
        fail("ERR_INVALID_REQUEST", "'%s' must be at most %s." % (name, le))
    return number


def req_bool(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    if not isinstance(body[name], bool):
        fail("ERR_INVALID_REQUEST", "'%s' must be a boolean." % name)
    return body[name]


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    if not isinstance(body[name], bool):
        fail("ERR_INVALID_REQUEST", "'%s' must be a boolean." % name)
    return body[name]


# ------------------------------------------------------------- datetimes -----

def req_dt(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    return _check_dt(body[name], name)


def opt_dt(body, name, default=None):
    if not _present(body, name):
        return default
    return _check_dt(body[name], name)


def _check_dt(value, name):
    moment = parse_iso(value) if isinstance(value, str) else None
    if moment is None:
        fail("ERR_INVALID_REQUEST", "'%s' must be an ISO 8601 instant." % name)
    return moment


def reject_field(body, name, reason):
    if name in body and body[name] is not None:
        fail("ERR_INVALID_REQUEST", reason)


# ------------------------------------------------------------ query args -----

def _int_param(raw, name):
    text = raw.strip()
    if not text:
        fail("ERR_INVALID_REQUEST", "'%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "'%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)


def pagination():
    """`limit` 1..100 (default 10) and `offset` >= 0 (default 0); never clamped."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _int_param(raw_limit, "limit")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _int_param(raw_offset, "offset")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "'offset' must be at least 0.")
    return limit, offset


def filter_value(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "'%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return raw


def paginate(records, limit, offset):
    return records[offset:offset + limit]
