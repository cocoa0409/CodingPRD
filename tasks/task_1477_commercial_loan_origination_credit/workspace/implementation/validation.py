"""Request body / query validation helpers (pipeline stage 4)."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError, ERR_VALIDATION

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _verr(msg):
    return ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1], msg)


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
    v = body.get(field, default)
    if v is None:
        return None
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


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise _verr("Field '%s' must be a boolean." % field)
    return v


def req_number(body, field):
    """Numeric (int or float, not bool). Returns Decimal."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _verr("Field '%s' is required and must be a number." % field)
    return Decimal(str(v))


def req_enum(body, field, members):
    v = body.get(field)
    if not isinstance(v, str) or v not in members:
        raise _verr("Field '%s' must be one of: %s." % (field, ", ".join(sorted(members))))
    return v


def opt_enum(body, field, members, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, members)


def parse_date_str(s, field):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise _verr("Field '%s' must be an ISO date (YYYY-MM-DD)." % field)
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise _verr("Field '%s' must be a valid ISO date (YYYY-MM-DD)." % field)


def req_date(body, field):
    if field not in body or body.get(field) is None:
        raise _verr("Field '%s' is required." % field)
    return parse_date_str(body.get(field), field)


def parse_datetime_str(s, field):
    if not isinstance(s, str):
        raise _verr("Field '%s' must be an ISO 8601 datetime." % field)
    t = s.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
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
