"""Request body / query validation helpers (pipeline stage 4).

All failures here are ERR_INVALID_REQUEST (HTTP 400) per the scaffold's
validation table.
"""
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def _verr(msg):
    return ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], msg)


def get_body(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise _verr("Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        raise _verr("Request body must be a JSON object.")
    return data


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise _verr("Field '%s' is required and must be a non-empty string." % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise _verr("Field '%s' must be a string." % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _verr("Field '%s' is required and must be an integer." % field)
    return v


def opt_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _verr("Field '%s' must be an integer." % field)
    return v


def req_int_pos(body, field):
    v = req_int(body, field)
    if v <= 0:
        raise _verr("Field '%s' must be a positive integer." % field)
    return v


def req_int_nonneg(body, field):
    v = req_int(body, field)
    if v < 0:
        raise _verr("Field '%s' must be a non-negative integer." % field)
    return v


def opt_int_nonneg(body, field, default=None):
    v = opt_int(body, field, default)
    if v is not None and v < 0:
        raise _verr("Field '%s' must be a non-negative integer." % field)
    return v


def req_number(body, field):
    """Numeric (int or float, not bool). Returns the raw JSON number so the
    input precision is preserved; calculations convert via Decimal(str(v))."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _verr("Field '%s' is required and must be a number." % field)
    return v


def opt_number(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field)


def req_enum(body, field, members):
    v = body.get(field)
    if not isinstance(v, str) or v not in members:
        raise _verr("Field '%s' must be one of: %s." % (field, ", ".join(sorted(members))))
    return v


def opt_enum(body, field, members, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, members)


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise _verr("Field '%s' is required and must be an array." % field)
    return v


def opt_list(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_list(body, field)


def req_str_list(body, field):
    v = req_list(body, field)
    for item in v:
        if not isinstance(item, str):
            raise _verr("Field '%s' must be an array of strings." % field)
    return v


def req_dict(body, field):
    v = body.get(field)
    if not isinstance(v, dict):
        raise _verr("Field '%s' is required and must be an object." % field)
    return v


def opt_dict(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_dict(body, field)


def parse_datetime_str(s, field):
    if not isinstance(s, str):
        raise _verr("Field '%s' must be an ISO 8601 datetime string." % field)
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise _verr("Field '%s' must be a parseable ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    if field not in body or body.get(field) is None:
        raise _verr("Field '%s' is required." % field)
    return parse_datetime_str(body.get(field), field)


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return parse_datetime_str(body.get(field), field)


def fk_or_404(collection, body, field, label, not_found_entry):
    """Pipeline stage 3 for body-carried foreign keys: a present string FK that
    references nothing fails existence before remaining well-formedness."""
    v = body.get(field)
    if isinstance(v, str) and collection.get(v) is None:
        raise ApiError(
            not_found_entry[0],
            not_found_entry[1],
            "%s '%s' does not exist." % (label, v),
        )


def parse_pagination():
    """limit/offset query params: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise _verr("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise _verr("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _verr("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise _verr("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Items must already be sorted; returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total
