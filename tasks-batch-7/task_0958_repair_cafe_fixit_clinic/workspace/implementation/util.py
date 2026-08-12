"""Request-body and query-string validation helpers.

Malformed payloads (missing required field, invalid enum, out-of-range
scalar, unparseable timestamp) are rejected with ERR_VALIDATION (HTTP 400).
"""

from flask import request

from db import parse_dt
from errors import ERR_VALIDATION, raise_err
from response import success


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def _fail(field, why):
    raise_err(ERR_VALIDATION, "Field '%s': %s" % (field, why))


def req(b, field):
    if field not in b or b[field] is None:
        _fail(field, "is required")
    return b[field]


def opt(b, field, default=None):
    v = b.get(field, default)
    return default if v is None else v


def as_str(value, field, required_len=False):
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if required_len and value == "":
        _fail(field, "must be a non-empty string")
    return value


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(value, field, lo=None, hi=None):
    if not _is_int(value):
        _fail(field, "must be an integer")
    if lo is not None and value < lo:
        _fail(field, "must be >= %s" % lo)
    if hi is not None and value > hi:
        _fail(field, "must be <= %s" % hi)
    return value


def as_num(value, field, lo=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(field, "must be a number")
    if lo is not None and value < lo:
        _fail(field, "must be >= %s" % lo)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        _fail(field, "must be a boolean")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        _fail(field, "must be one of %s" % sorted(allowed))
    return value


def as_dt(value, field):
    """Validate that value is a parseable ISO-8601 datetime; return raw string."""
    if not isinstance(value, str):
        _fail(field, "must be an ISO-8601 datetime string")
    try:
        parse_dt(value)
    except (ValueError, TypeError):
        _fail(field, "must be a valid ISO-8601 datetime")
    return value


def list_response(records, serializer, filters):
    """Apply filters, sort by created_at ascending, paginate (limit/offset).

    filters: list of (query_param_name, record_field_name) exact matches.
    """
    args = request.args
    limit, offset = 10, 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise_err(ERR_VALIDATION, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "Query parameter 'limit' must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise_err(ERR_VALIDATION, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "Query parameter 'offset' must be >= 0")

    recs = sorted(records, key=lambda r: r["_seq"])
    for param, field in filters:
        if param in args:
            want = args[param]
            recs = [r for r in recs if str(r.get(field)) == want]

    total = len(recs)
    page = recs[offset : offset + limit]
    data = [serializer(r) for r in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success(data, 200, "array", pagination)
