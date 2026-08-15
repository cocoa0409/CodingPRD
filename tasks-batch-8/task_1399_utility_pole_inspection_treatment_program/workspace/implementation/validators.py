from flask import request

from errors import ApiError
from calc import parse_dt, parse_date


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def req_field(d, name):
    if name not in d or d[name] is None:
        bad("Missing required field: %s" % name)
    return d[name]


def opt_field(d, name, default=None):
    if name not in d or d[name] is None:
        return default
    return d[name]


def as_str(v, name, non_empty=False):
    if not isinstance(v, str):
        bad("Field %s must be a string" % name)
    if non_empty and v == "":
        bad("Field %s must be non-empty" % name)
    return v


def as_int(v, name, mn=None, mx=None):
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %s must be an integer" % name)
    if mn is not None and v < mn:
        bad("Field %s must be >= %s" % (name, mn))
    if mx is not None and v > mx:
        bad("Field %s must be <= %s" % (name, mx))
    return v


def as_num(v, name, mn=None, mx=None, min_exclusive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("Field %s must be a number" % name)
    if mn is not None:
        if min_exclusive and not (v > mn):
            bad("Field %s must be > %s" % (name, mn))
        if not min_exclusive and v < mn:
            bad("Field %s must be >= %s" % (name, mn))
    if mx is not None and v > mx:
        bad("Field %s must be <= %s" % (name, mx))
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        bad("Field %s must be a boolean" % name)
    return v


def as_enum(v, name, values):
    if not isinstance(v, str) or v not in values:
        bad("Field %s must be one of %s" % (name, sorted(values)))
    return v


def as_list(v, name):
    if not isinstance(v, list):
        bad("Field %s must be an array" % name)
    return v


def as_str_list(v, name):
    as_list(v, name)
    for item in v:
        if not isinstance(item, str):
            bad("Field %s must be an array of strings" % name)
    return v


def as_date_str(v, name):
    if parse_date(v) is None:
        bad("Field %s must be a YYYY-MM-DD date" % name)
    return v


def as_dt(v, name):
    d = parse_dt(v)
    if d is None:
        bad("Field %s must be an ISO 8601 datetime" % name)
    return d


def pagination():
    """limit (default 10, min 1, max 100) / offset (default 0)."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            bad("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            bad("Query parameter limit out of range (1..100)")
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            bad("Query parameter offset must be an integer")
        if offset < 0:
            bad("Query parameter offset must be >= 0")
    return limit, offset


def apply_filters(records, filters):
    """filters: list of (field_name, raw_query_value); None means absent."""
    out = []
    for r in records:
        match = True
        for field, value in filters:
            if value is not None and r.get(field) != value:
                match = False
                break
        if match:
            out.append(r)
    out.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return out
