"""Body-shape validation, pagination parsing, and lookup helpers."""
from datetime import datetime, date, timezone

from flask import request

import store
from errors import ApiError

_MISSING = object()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def lookup(collection, row_id, err_id):
    row = store.DB[collection].get(row_id)
    if row is None:
        raise ApiError(err_id, "Resource not found: %s" % row_id)
    return row


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        raise ApiError("ERR_VALIDATION", "Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def reject_protected(body, allowed, protected):
    for key in body:
        if key not in allowed and key in protected:
            raise ApiError("ERR_VALIDATION",
                           "Field '%s' may not be supplied." % key)


def _fail(field, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, why))


def req_str(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _fail(field, "is required")
    if not isinstance(v, str) or v == "":
        _fail(field, "must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING or v is None:
        return None
    if not isinstance(v, str):
        _fail(field, "must be a string")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _fail(field, "is required")
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(field, "must be an integer")
    if minimum is not None and v < minimum:
        _fail(field, "must be >= %s" % minimum)
    if maximum is not None and v > maximum:
        _fail(field, "must be <= %s" % maximum)
    return v


def opt_int(body, field, minimum=None, maximum=None):
    if body.get(field, _MISSING) is _MISSING:
        return _MISSING
    if body.get(field) is None:
        _fail(field, "must be an integer")
    return req_int(body, field, minimum, maximum)


def req_number(body, field, minimum=None, maximum=None,
               min_exclusive=False, max_inclusive=True):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _fail(field, "is required")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(field, "must be a number")
    if minimum is not None:
        if min_exclusive and not (v > minimum):
            _fail(field, "must be > %s" % minimum)
        if not min_exclusive and v < minimum:
            _fail(field, "must be >= %s" % minimum)
    if maximum is not None:
        if max_inclusive and v > maximum:
            _fail(field, "must be <= %s" % maximum)
        if not max_inclusive and not (v < maximum):
            _fail(field, "must be < %s" % maximum)
    return v


def opt_number(body, field, minimum=None, maximum=None,
               min_exclusive=False, max_inclusive=True):
    if body.get(field, _MISSING) is _MISSING:
        return _MISSING
    return req_number(body, field, minimum, maximum, min_exclusive, max_inclusive)


def req_bool(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _fail(field, "is required")
    if not isinstance(v, bool):
        _fail(field, "must be a boolean")
    return v


def opt_bool(body, field):
    if body.get(field, _MISSING) is _MISSING:
        return _MISSING
    return req_bool(body, field)


def req_enum(body, field, choices):
    v = req_str(body, field)
    if v not in choices:
        _fail(field, "must be one of %s" % sorted(choices))
    return v


def opt_enum(body, field, choices):
    if body.get(field, _MISSING) is _MISSING:
        return _MISSING
    return req_enum(body, field, choices)


def req_date(body, field):
    v = req_str(body, field)
    try:
        return date.fromisoformat(v)
    except Exception:
        _fail(field, "must be an ISO 8601 calendar date (YYYY-MM-DD)")


def parse_datetime(field, value):
    if not isinstance(value, str):
        _fail(field, "must be an ISO 8601 datetime string")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except Exception:
        _fail(field, "must be a well-formed ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _fail(field, "is required")
    return parse_datetime(field, v)


# ---------------------------------------------------------------------------
# Pagination + list assembly
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = parse_pagination()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    items = [serializer(r) for r in page]
    has_more = (offset + len(page)) < total
    return items, limit, offset, total, has_more
