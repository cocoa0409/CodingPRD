"""Request-shape validation helpers (validation ladder step 3)."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

_MISSING = object()

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def get_string(data, name, required=True, min_len=None, max_len=None,
               pattern=None, default=None):
    if not present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    if pattern is not None and not pattern.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' is malformed." % name)
    return value


def get_enum(data, name, members, required=True, default=None):
    value = get_string(data, name, required=required, default=_MISSING)
    if value is _MISSING:
        return default
    if value not in members:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, sorted(members)))
    return value


def get_bool(data, name, required=False, default=None):
    if not present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def get_int(data, name, required=True, default=None, minimum=None,
            exclusive_minimum=None, maximum=None):
    if not present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % name)
    return value


def get_number(data, name, required=True, default=None, minimum=None,
               exclusive_minimum=None, maximum=None, exclusive_maximum=None,
               places=None):
    if not present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if not dec.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % name)
    if places is not None:
        exponent = dec.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > places:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must carry at most %d decimal places." % (name, places))
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % name)
    if exclusive_maximum is not None and dec >= Decimal(str(exclusive_maximum)):
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be less than %s." % (name, exclusive_maximum))
    return dec


def get_enum_array(data, name, members, required=True, default=None):
    if not present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, list) or not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in members:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must be a subset of %s." % (name, sorted(members)))
        if item in seen:
            fail("ERR_INVALID_REQUEST", "Field '%s' must not contain duplicates." % name)
        seen.add(item)
    return list(value)


def get_month(data, name, required=True, default=None):
    value = get_string(data, name, required=required, default=_MISSING)
    if value is _MISSING:
        return default
    if not MONTH_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM month." % name)
    return value


def get_date(data, name, required=True, default=None):
    value = get_string(data, name, required=required, default=_MISSING)
    if value is _MISSING:
        return default
    if not DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date." % name)
    try:
        date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a valid calendar date." % name)
    return value


def parse_date(value):
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def month_after(month):
    year = int(month[0:4])
    mon = int(month[5:7])
    if mon == 12:
        return "%04d-01" % (year + 1)
    return "%04d-%02d" % (year, mon + 1)


# ---------------------------------------------------------------- query params

def pagination():
    """PRD 2.3: limit defaults to 10, min 1, max 100; offset defaults to 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def enum_filter(name, members):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a recognised value." % name)
    return value


def raw_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def month_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if not MONTH_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a YYYY-MM month." % name)
    return value


def date_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if not DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an ISO 8601 date." % name)
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
