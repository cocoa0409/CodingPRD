"""Schema-level validation (PRD section 2.7 step 3).

Every failure here raises ERR_INVALID_REQUEST (HTTP 400).  Numbers are read
from the raw request body with `parse_float=Decimal` so that the declared
decimal-place limits can be enforced against the literal the client sent.
"""

import json
from decimal import Decimal

from flask import request

from errors import ApiError
from util import D, parse_iso

MISSING = object()


def bad(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def body():
    """Parse the JSON request body into a dict; an absent body is {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        bad("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def _present(src, name):
    return name in src and src[name] is not None


def req_present(src, name):
    if not _present(src, name):
        bad("field '%s' is required" % name)


def get_str(src, name, required=True, default=None, min_len=None, max_len=None):
    if not _present(src, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = src[name]
    if not isinstance(value, str):
        bad("field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("field '%s' is shorter than %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("field '%s' is longer than %d characters" % (name, max_len))
    return value


def get_enum(src, name, allowed, required=True, default=None):
    if not _present(src, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = src[name]
    if not isinstance(value, str) or value not in allowed:
        bad("field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def get_int(src, name, required=True, default=None, min_=None, max_=None):
    if not _present(src, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = src[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            bad("field '%s' must be an integer" % name)
    if min_ is not None and value < min_:
        bad("field '%s' must be >= %s" % (name, min_))
    if max_ is not None and value > max_:
        bad("field '%s' must be <= %s" % (name, max_))
    return value


def get_num(src, name, places, required=True, default=None,
            gt=None, ge=None, lt=None, le=None):
    if not _present(src, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = src[name]
    if isinstance(value, bool):
        bad("field '%s' must be a number" % name)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        value = D(value)
    else:
        bad("field '%s' must be a number" % name)
    if value != value:  # NaN guard
        bad("field '%s' must be a number" % name)
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        bad("field '%s' must be a number" % name)
    if -exponent > places:
        bad("field '%s' carries more than %d decimal places" % (name, places))
    if gt is not None and not value > D(gt):
        bad("field '%s' must be > %s" % (name, gt))
    if ge is not None and not value >= D(ge):
        bad("field '%s' must be >= %s" % (name, ge))
    if lt is not None and not value < D(lt):
        bad("field '%s' must be < %s" % (name, lt))
    if le is not None and not value <= D(le):
        bad("field '%s' must be <= %s" % (name, le))
    return value


def get_bool(src, name, required=True, default=None):
    if not _present(src, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = src[name]
    if not isinstance(value, bool):
        bad("field '%s' must be a boolean" % name)
    return value


def get_dt(src, name, required=True, default=None):
    if not _present(src, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = src[name]
    parsed = parse_iso(value)
    if parsed is None:
        bad("field '%s' must be an ISO-8601 UTC instant ending in Z" % name)
    return parsed


def window(start, end, start_name, end_name):
    if not end > start:
        bad("'%s' must be strictly after '%s'" % (end_name, start_name))


# ------------------------------------------------------------------ query ----

def query_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("query parameter 'limit' must be an integer")
        if str(limit) != str(raw).strip():
            bad("query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("query parameter 'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("query parameter 'offset' must be an integer")
        if str(offset) != str(raw).strip():
            bad("query parameter 'offset' must be an integer")
        if offset < 0:
            bad("query parameter 'offset' may not be negative")
    return limit, offset


def query_enum(name, allowed, required=False):
    args = request.args
    if name not in args:
        if required:
            bad("query parameter '%s' is required" % name)
        return None
    value = args.get(name)
    if value not in allowed:
        bad("query parameter '%s' must be one of %s"
            % (name, ", ".join(sorted(allowed))))
    return value


def query_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_bool(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value == "true":
        return True
    if value == "false":
        return False
    bad("query parameter '%s' must be true or false" % name)
