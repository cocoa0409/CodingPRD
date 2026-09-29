"""Request shape validation -- ERR_INVALID_REQUEST, priority 3 of PRD 2.10."""
from decimal import Decimal, InvalidOperation

from flask import request

from common import (PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX, PAGE_LIMIT_MIN, dec,
                    parse_date_str, parse_iso, rhu)
from errors import ApiError


def fail(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("request body must be a JSON object")
    return parsed


def present(data, field):
    if field not in data or data[field] is None:
        fail("field '%s' is required" % field)
    return data[field]


def req_str(data, field, max_len=None):
    value = present(data, field)
    if not isinstance(value, str):
        fail("field '%s' must be a string" % field)
    if value.strip() == "":
        fail("field '%s' must be non-empty" % field)
    if max_len is not None and len(value) > max_len:
        fail("field '%s' exceeds %d characters" % (field, max_len))
    return value


def opt_str(data, field, max_len=None, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        fail("field '%s' must be a string" % field)
    if max_len is not None and len(value) > max_len:
        fail("field '%s' exceeds %d characters" % (field, max_len))
    return value


def req_id(data, field):
    value = present(data, field)
    if not isinstance(value, str) or value.strip() == "":
        fail("field '%s' must be a non-empty string identifier" % field)
    return value


def opt_id(data, field):
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        fail("field '%s' must be a non-empty string identifier" % field)
    return value


def req_enum(data, field, allowed):
    value = present(data, field)
    if not isinstance(value, str):
        fail("field '%s' must be a string" % field)
    if value not in allowed:
        fail("field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def req_bool(data, field, default=None):
    if field not in data or data[field] is None:
        if default is None:
            fail("field '%s' is required" % field)
        return default
    value = data[field]
    if not isinstance(value, bool):
        fail("field '%s' must be a boolean" % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    value = present(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("field '%s' must be at least %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("field '%s' must be at most %s" % (field, maximum))
    return value


def _number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("field '%s' must be a number" % field)
    try:
        return dec(value)
    except (InvalidOperation, ValueError):
        fail("field '%s' must be a number" % field)


def req_number(data, field, places, minimum=None, maximum=None,
               exclusive_min=None):
    value = _number(field, present(data, field))
    value = rhu(value, places)
    if exclusive_min is not None and not value > dec(exclusive_min):
        fail("field '%s' must be greater than %s" % (field, exclusive_min))
    if minimum is not None and value < dec(minimum):
        fail("field '%s' must be at least %s" % (field, minimum))
    if maximum is not None and value > dec(maximum):
        fail("field '%s' must be at most %s" % (field, maximum))
    return value


def opt_number(data, field, places, default=None, minimum=None, maximum=None,
               exclusive_min=None):
    if field not in data or data[field] is None:
        return default
    return req_number(data, field, places, minimum=minimum, maximum=maximum,
                      exclusive_min=exclusive_min)


def req_date(data, field):
    value = present(data, field)
    if not isinstance(value, str):
        fail("field '%s' must be a YYYY-MM-DD date string" % field)
    try:
        return parse_date_str(value)
    except Exception:
        fail("field '%s' must be a YYYY-MM-DD date string" % field)


def req_instant(data, field):
    value = present(data, field)
    if not isinstance(value, str):
        fail("field '%s' must be an ISO 8601 instant" % field)
    try:
        return parse_iso(value)
    except Exception:
        fail("field '%s' must be an ISO 8601 instant" % field)


def req_enum_array(data, field, allowed):
    value = present(data, field)
    if not isinstance(value, list):
        fail("field '%s' must be an array" % field)
    if len(value) < 1:
        fail("field '%s' must hold at least one element" % field)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("field '%s' items must be one of %s" % (field, ", ".join(allowed)))
    return list(value)


# ------------------------------------------------------------------ queries
def _int_arg(name, raw):
    text = raw.strip()
    if text == "":
        fail("query parameter '%s' must be an integer" % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("query parameter '%s' must be an integer" % name)
    return -int(digits) if negative else int(digits)


def pagination():
    limit = PAGE_LIMIT_DEFAULT
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _int_arg("limit", raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("limit must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _int_arg("offset", raw_offset)
        if offset < 0:
            fail("offset must be at least 0")
    return limit, offset


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def str_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def int_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    return _int_arg(name, value)


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total
