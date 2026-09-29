"""Request-shape validation (rung 3 of the rejection ladder, PRD 2.11)."""

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST, fail
from util import D, parse_iso_dt, parse_ymd

MISSING = object()


def bad(message):
    fail(ERR_INVALID_REQUEST, message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            bad("Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def _present(b, name):
    return name in b and b[name] is not None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def f_str(b, name, required=True, default=None, allow_empty=False):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, str):
        bad("Field '%s' must be a string" % name)
    if not allow_empty and v == "":
        bad("Field '%s' must not be empty" % name)
    return v


def f_enum(b, name, choices, required=True, default=None):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, str) or v not in choices:
        bad("Field '%s' must be one of %s" % (name, ", ".join(choices)))
    return v


def f_num(b, name, required=True, default=None, gt=None, ge=None, le=None, lt=None):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not _is_num(v):
        bad("Field '%s' must be a number" % name)
    d = D(v)
    if gt is not None and not d > D(gt):
        bad("Field '%s' must be greater than %s" % (name, gt))
    if ge is not None and not d >= D(ge):
        bad("Field '%s' must be at least %s" % (name, ge))
    if lt is not None and not d < D(lt):
        bad("Field '%s' must be less than %s" % (name, lt))
    if le is not None and not d <= D(le):
        bad("Field '%s' must be at most %s" % (name, le))
    return d


def f_int(b, name, required=True, default=None, ge=None, gt=None, le=None, choices=None):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, int) or isinstance(v, bool):
        bad("Field '%s' must be an integer" % name)
    if choices is not None and v not in choices:
        bad("Field '%s' must be one of %s" % (name, choices))
    if gt is not None and not v > gt:
        bad("Field '%s' must be greater than %s" % (name, gt))
    if ge is not None and not v >= ge:
        bad("Field '%s' must be at least %s" % (name, ge))
    if le is not None and not v <= le:
        bad("Field '%s' must be at most %s" % (name, le))
    return v


def f_bool(b, name, required=False, default=None):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, bool):
        bad("Field '%s' must be a boolean" % name)
    return v


def f_date(b, name, required=True, default=None):
    """A YYYY-MM-DD calendar date; returns the canonical string."""
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, str) or parse_ymd(v) is None:
        bad("Field '%s' must be a date in YYYY-MM-DD form" % name)
    return v.strip()


def f_datetime(b, name, required=True, default=None):
    """An ISO 8601 UTC instant; returns (raw string, naive UTC datetime)."""
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default, None
    v = b[name]
    parsed = parse_iso_dt(v) if isinstance(v, str) else None
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC datetime" % name)
    return v, parsed


def f_num_array(b, name, required=False, default=None, gt=None):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, list):
        bad("Field '%s' must be an array" % name)
    out = []
    for item in v:
        if not _is_num(item):
            bad("Field '%s' must be an array of numbers" % name)
        d = D(item)
        if gt is not None and not d > D(gt):
            bad("Every entry of '%s' must be greater than %s" % (name, gt))
        out.append(d)
    return out


def f_str_array(b, name, required=False, default=None):
    if not _present(b, name):
        if required:
            bad("Field '%s' is required" % name)
        return default
    v = b[name]
    if not isinstance(v, list):
        bad("Field '%s' must be an array" % name)
    for item in v:
        if not isinstance(item, str):
            bad("Field '%s' must be an array of strings" % name)
    return list(v)


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0). PRD 2.3."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative")
    return limit, offset


def q_enum(name, choices):
    """An optional enum query filter; an unknown member is a malformed request."""
    if name not in request.args:
        return None
    v = request.args.get(name)
    if v not in choices:
        bad("Query parameter '%s' must be one of %s" % (name, ", ".join(choices)))
    return v


def q_date(name):
    if name not in request.args:
        return None
    v = request.args.get(name)
    if parse_ymd(v) is None:
        bad("Query parameter '%s' must be a date in YYYY-MM-DD form" % name)
    return v


def q_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)
