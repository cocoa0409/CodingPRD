"""Shared helpers: JSON body access, field validation, datetime handling, pagination.

Validation band order (PRD section 2.9): authentication (401) -> syntactic body
validation (400) -> authorization (403) -> existence (404) -> state (409) ->
business safety -> temporal -> constraints -> referential -> fiscal.
The helpers below implement the syntactic band (ERR_INVALID_REQUEST / 400).
"""

import json
from datetime import datetime, date, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

UTC = timezone.utc


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime; naive values are read as UTC."""
    if not isinstance(value, str):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value, field):
    """Parse a YYYY-MM-DD calendar date."""
    if not isinstance(value, str):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s must be a YYYY-MM-DD date string" % field)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is not a valid YYYY-MM-DD date" % field)


def json_body(required=False):
    """Return the request JSON object; empty body is {} unless required."""
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        if required:
            raise ApiError(400, ERR_INVALID_REQUEST, "request body is required")
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ApiError(400, ERR_INVALID_REQUEST, "request body is not valid JSON")
    if not isinstance(data, dict):
        raise ApiError(400, ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is required and must be a string" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not _is_int(v):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is required and must be an integer" % field)
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s must be an integer" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is required and must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "%s is required and must be one of %s" % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(400, ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return v


def req_dt(body, field):
    if field not in body or body.get(field) is None:
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is required" % field)
    return parse_datetime(body.get(field), field)


def opt_dt(body, field):
    v = body.get(field)
    if v is None:
        return None
    return parse_datetime(v, field)


def req_num(body, field):
    v = body.get(field)
    if not _is_num(v):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s is required and must be a number" % field)
    return v


def opt_num(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not _is_num(v):
        raise ApiError(400, ERR_INVALID_REQUEST, "%s must be a number" % field)
    return v


def pagination_params():
    """limit/offset per PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(400, ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(400, ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (creation sequence as stable tie-break) and slice."""
    from envelope import success_list
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return limit, offset, total, page
