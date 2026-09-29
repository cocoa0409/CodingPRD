"""Schema validation helpers - validation priority 30 (ERR_INVALID_REQUEST)."""

import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_dt
from errors import ApiError, invalid

_INT_RE = re.compile(r"^[+-]?\d+$")


def body_json():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        invalid("request body is not valid JSON")
    if not isinstance(parsed, dict):
        invalid("request body must be a JSON object")
    return parsed


def present(body, name):
    return name in body and body[name] is not None


def require(body, name):
    if not present(body, name):
        invalid("field '%s' is required" % name)
    return body[name]


def optional(body, name, default=None):
    if not present(body, name):
        return default
    return body[name]


def as_str(value, name, min_len=None, max_len=None):
    if not isinstance(value, str):
        invalid("field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        invalid("field '%s' must have at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("field '%s' must have at most %d characters" % (name, max_len))
    return value


def as_pattern(value, name, pattern):
    text = as_str(value, name)
    if not re.match(pattern, text):
        invalid("field '%s' does not match %s" % (name, pattern))
    return text


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        invalid("field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("field '%s' must be <= %s" % (name, maximum))
    return value


def as_decimal(value, name, places, gt=None, ge=None, le=None, lt=None):
    if isinstance(value, bool):
        invalid("field '%s' must be a number" % name)
    if isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, Decimal):
        d = value
    else:
        invalid("field '%s' must be a number" % name)
    try:
        if not d.is_finite():
            invalid("field '%s' must be a finite number" % name)
    except InvalidOperation:
        invalid("field '%s' must be a number" % name)
    exponent = d.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        invalid("field '%s' accepts at most %d decimal places" % (name, places))
    if gt is not None and not d > Decimal(str(gt)):
        invalid("field '%s' must be > %s" % (name, gt))
    if ge is not None and not d >= Decimal(str(ge)):
        invalid("field '%s' must be >= %s" % (name, ge))
    if le is not None and not d <= Decimal(str(le)):
        invalid("field '%s' must be <= %s" % (name, le))
    if lt is not None and not d < Decimal(str(lt)):
        invalid("field '%s' must be < %s" % (name, lt))
    return d.quantize(Decimal(1).scaleb(-places))


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        invalid("field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        invalid("field '%s' must be a boolean" % name)
    return value


def as_code_subset(value, name, allowed):
    if not isinstance(value, list):
        invalid("field '%s' must be an array" % name)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("field '%s' contains an unknown code" % name)
        if item in seen:
            invalid("field '%s' must not contain duplicates" % name)
        seen.append(item)
    return list(value)


def as_datetime(value, name):
    parsed = parse_dt(value)
    if parsed is None:
        invalid("field '%s' must be an ISO 8601 UTC timestamp" % name)
    return parsed


def query_bool(name):
    """Parse a boolean query parameter; absent -> None."""
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    invalid("query parameter '%s' must be true or false" % name)


def paging():
    """limit default 10 (1..100); offset default 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        text = raw_limit.strip()
        if not _INT_RE.match(text):
            invalid("limit must be an integer")
        limit = int(text)
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        text = raw_offset.strip()
        if not _INT_RE.match(text):
            invalid("offset must be an integer")
        offset = int(text)
        if offset < 0:
            invalid("offset must be >= 0")
    return limit, offset


def window(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
