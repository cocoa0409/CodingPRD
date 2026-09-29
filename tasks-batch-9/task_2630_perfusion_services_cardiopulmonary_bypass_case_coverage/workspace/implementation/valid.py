"""Request-shape validation: PRD 2.8 rungs 6 (ERR_INVALID_REQUEST),
7 (ERR_INVALID_FIELD_VALUE) and 8 (ERR_INVALID_PAGINATION)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from envelope import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ApiError

BAD_REQUEST = "ERR_INVALID_REQUEST"
BAD_VALUE = "ERR_INVALID_FIELD_VALUE"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def payload():
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(BAD_VALUE, "Request body must be a JSON object.")
    return body


def require(body, *names):
    """Rung 6: every required field must be present and non-null."""
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)


def _bad(name, why):
    return ApiError(BAD_VALUE, "Field '%s' %s." % (name, why))


def vstr(body, name, max_len=None, allow_empty=False, default=None, required=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise _bad(name, "must be a string")
    if not allow_empty and v.strip() == "":
        raise _bad(name, "must not be empty")
    if max_len is not None and len(v) > max_len:
        raise _bad(name, "must be at most %d characters" % max_len)
    return v


def venum(body, name, allowed, default=None, required=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return v


def vbool(body, name, default=None, required=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise _bad(name, "must be a boolean")
    return v


def vint(body, name, minimum=None, maximum=None, default=None, required=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise _bad(name, "must be an integer")
    if minimum is not None and v < minimum:
        raise _bad(name, "must be at least %s" % minimum)
    if maximum is not None and v > maximum:
        raise _bad(name, "must be at most %s" % maximum)
    return v


def to_dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def vnum(body, name, minimum=None, maximum=None, max_dp=None, default=None,
         required=False, exclusive_max=None):
    """Returns a Decimal (or the supplied default when absent)."""
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _bad(name, "must be a number")
    d = to_dec(v)
    if d is None or not d.is_finite():
        raise _bad(name, "must be a finite number")
    if minimum is not None and d < Decimal(str(minimum)):
        raise _bad(name, "must be at least %s" % minimum)
    if maximum is not None and d > Decimal(str(maximum)):
        raise _bad(name, "must be at most %s" % maximum)
    if exclusive_max is not None and d >= Decimal(str(exclusive_max)):
        raise _bad(name, "must be below %s" % exclusive_max)
    if max_dp is not None:
        exp = d.as_tuple().exponent
        if isinstance(exp, int) and -exp > max_dp:
            raise _bad(name, "must carry at most %d decimal places" % max_dp)
    return d


def parse_dt(value, name):
    if not isinstance(value, str):
        raise _bad(name, "must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise _bad(name, "must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def vdt(body, name, default=None, required=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    return parse_dt(body[name], name)


def vdate(body, name, default=None, required=False):
    """Calendar date (YYYY-MM-DD), returned as a date object."""
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if not isinstance(v, str) or not DATE_RE.match(v.strip()):
        raise _bad(name, "must be a calendar date formatted YYYY-MM-DD")
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise _bad(name, "must be a valid calendar date")


def varray(body, name, min_len=None, max_len=None, default=None, required=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(BAD_REQUEST, "Field '%s' is required." % name)
        return default
    v = body[name]
    if not isinstance(v, list):
        raise _bad(name, "must be an array")
    if min_len is not None and len(v) < min_len:
        raise _bad(name, "must carry at least %d entries" % min_len)
    if max_len is not None and len(v) > max_len:
        raise _bad(name, "must carry at most %d entries" % max_len)
    return v


def pagination():
    """Rung 8.  Non-numeric or out-of-range limit/offset is ERR_INVALID_PAGINATION."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be zero or greater.")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]
