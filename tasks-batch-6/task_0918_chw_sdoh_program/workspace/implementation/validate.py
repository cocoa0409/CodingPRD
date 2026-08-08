"""Rung-5 payload shape and domain primitives (PRD §2.5 rung 5, §3 field rules).

Every failure here raises ERR_VALIDATION (HTTP 400).  There is no dedicated
invalid-enum error in this catalogue, so enum-membership failures are routed
through :func:`enum_value` / :func:`opt_enum` to the same ERR_VALIDATION.
"""

import re

from clockutil import parse_iso
from errors import ApiError, ERR_VALIDATION

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
ZIP_RE = re.compile(r"^\d{5}$")

MISSING = object()


def bad(message):
    raise ApiError(ERR_VALIDATION, message)


def present(body, key):
    return isinstance(body, dict) and key in body and body[key] is not None


def _raw(body, key):
    if not isinstance(body, dict):
        return MISSING
    if key not in body:
        return MISSING
    return body[key]


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_str(body, key, allow_empty=False):
    value = _raw(body, key)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if not allow_empty and value.strip() == "":
        bad("%s must be a non-empty string" % key)
    return value


def opt_str(body, key, default=None, allow_empty=True):
    value = _raw(body, key)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if not allow_empty and value.strip() == "":
        bad("%s must be a non-empty string" % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not is_int(value):
        bad("%s must be an integer" % key)
    _range(key, value, minimum, maximum)
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        return default
    if not is_int(value):
        bad("%s must be an integer" % key)
    _range(key, value, minimum, maximum)
    return value


def req_num(body, key, minimum=None, maximum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not is_num(value):
        bad("%s must be a number" % key)
    _range(key, value, minimum, maximum)
    return value


def opt_num(body, key, default=None, minimum=None, maximum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        return default
    if not is_num(value):
        bad("%s must be a number" % key)
    _range(key, value, minimum, maximum)
    return value


def _range(key, value, minimum, maximum):
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (key, maximum))


def opt_bool(body, key, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, bool):
        bad("%s must be a boolean" % key)
    return value


def req_enum(body, key, members):
    value = req_str(body, key)
    return enum_value(key, value, members)


def opt_enum(body, key, members, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    return enum_value(key, value, members)


def enum_value(key, value, members):
    """The single shared enum-membership gate; every enum failure lands here."""
    if value not in members:
        bad("%s must be one of %s" % (key, ", ".join(sorted(members))))
    return value


def req_obj(body, key):
    value = _raw(body, key)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not isinstance(value, dict):
        bad("%s must be an object" % key)
    return value


def req_list(body, key):
    value = _raw(body, key)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    return value


def opt_list(body, key, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        return list(default) if default is not None else None
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    return value


def code_array(key, values):
    """Array of non-empty uppercase codes."""
    for item in values:
        if not isinstance(item, str) or item.strip() == "":
            bad("%s entries must be non-empty strings" % key)
        if item != item.upper():
            bad("%s entries must be uppercase" % key)
    return values


def zip_array(key, values):
    if not values:
        bad("%s must be a non-empty array" % key)
    for item in values:
        if not isinstance(item, str) or not ZIP_RE.match(item):
            bad("%s entries must be 5-digit ZIP codes" % key)
    return values


def req_zip(body, key):
    value = req_str(body, key)
    if not ZIP_RE.match(value):
        bad("%s must be exactly 5 numeric characters" % key)
    return value


def req_date(body, key):
    value = req_str(body, key)
    if not DATE_RE.match(value):
        bad("%s must be a YYYY-MM-DD date" % key)
    return value


def req_month(body, key):
    value = req_str(body, key)
    if not MONTH_RE.match(value):
        bad("%s must be a YYYY-MM month" % key)
    return value


def req_instant(body, key):
    value = req_str(body, key)
    if parse_iso(value) is None:
        bad("%s must be an ISO 8601 instant" % key)
    return value


def pagination(args):
    """limit 1..100 (default 10) and offset >= 0 (default 0)."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
