"""Request-shape validation — admission ladder rung 4 (PRD 2.7)."""

from datetime import datetime, timezone

from flask import request

from calc import rhu
from errors import ApiError
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

_SENTINEL = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad("Request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, minlen=1, maxlen=None):
    if not _present(body, name):
        bad("Field '%s' is required" % name)
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % name)
    if len(value) < minlen:
        bad("Field '%s' must be at least %d characters" % (name, minlen))
    if maxlen is not None and len(value) > maxlen:
        bad("Field '%s' must be at most %d characters" % (name, maxlen))
    return value


def opt_str(body, name, default=None, minlen=1, maxlen=None):
    if not _present(body, name):
        return default
    return req_str(body, name, minlen=minlen, maxlen=maxlen)


def req_id(body, name):
    return req_str(body, name, minlen=1)


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    return req_str(body, name, minlen=1)


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        bad("Field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def _as_number(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % name)
    try:
        f = float(value)
    except Exception:
        bad("Field '%s' must be a number" % name)
    if f != f or f in (float("inf"), float("-inf")):
        bad("Field '%s' must be a finite number" % name)
    return value


def req_num(body, name, places, gt=None, ge=None, lt=None, le=None):
    if not _present(body, name):
        bad("Field '%s' is required" % name)
    value = _as_number(name, body[name])
    rounded = float(rhu(value, places))
    _range_check(name, rounded, gt, ge, lt, le)
    return rounded


def opt_num(body, name, places, default=None, gt=None, ge=None, lt=None, le=None):
    if not _present(body, name):
        return default
    return req_num(body, name, places, gt=gt, ge=ge, lt=lt, le=le)


def req_int(body, name, gt=None, ge=None, lt=None, le=None):
    if not _present(body, name):
        bad("Field '%s' is required" % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be an integer" % name)
    if isinstance(value, float):
        if not float(value).is_integer():
            bad("Field '%s' must be an integer" % name)
        value = int(value)
    _range_check(name, value, gt, ge, lt, le)
    return int(value)


def opt_int(body, name, default=None, gt=None, ge=None, lt=None, le=None):
    if not _present(body, name):
        return default
    return req_int(body, name, gt=gt, ge=ge, lt=lt, le=le)


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % name)
    return value


def req_str_list(body, name):
    if not _present(body, name):
        bad("Field '%s' is required" % name)
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % name)
    for item in value:
        if not isinstance(item, str) or not item:
            bad("Field '%s' must be an array of identifier strings" % name)
    return list(value)


def _range_check(name, value, gt, ge, lt, le):
    if gt is not None and not value > gt:
        bad("Field '%s' must be greater than %s" % (name, gt))
    if ge is not None and not value >= ge:
        bad("Field '%s' must be greater than or equal to %s" % (name, ge))
    if lt is not None and not value < lt:
        bad("Field '%s' must be less than %s" % (name, lt))
    if le is not None and not value <= le:
        bad("Field '%s' must be less than or equal to %s" % (name, le))


def parse_instant(name, raw):
    if not isinstance(raw, str) or not raw.strip():
        bad("Field '%s' must be an ISO 8601 UTC timestamp" % name)
    text = raw.strip()
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except Exception:
        bad("Field '%s' must be an ISO 8601 UTC timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_instant(body, name):
    if not _present(body, name):
        bad("Field '%s' is required" % name)
    return parse_instant(name, body[name]), body[name]


# ---- query string ---------------------------------------------------------

def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            bad("Query parameter 'limit' must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad(
                "Query parameter 'limit' must be between %d and %d"
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must be greater than or equal to 0")
    return limit, offset


def filter_enum(name, allowed):
    args = request.args
    if name not in args:
        return None
    value = args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
