"""Shared helpers: timestamps, request body validation, pagination."""

from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_VALIDATION


def parse_dt(value, field):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ApiError(ERR_VALIDATION, 400,
                           "field '%s' is not a valid ISO 8601 timestamp" % field)
    else:
        raise ApiError(ERR_VALIDATION, 400,
                       "field '%s' must be an ISO 8601 timestamp string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def get_body():
    """Return the JSON request body as a dict; empty/absent body -> {}."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_VALIDATION, 400, "request body must be a JSON object")
    return body


def req_field(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_VALIDATION, 400, "missing required field: %s" % field)
    return body[field]


def req_str(body, field):
    value = req_field(body, field)
    if not isinstance(value, str) or not value:
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be a non-empty string" % field)
    return value


def req_bool(body, field):
    value = req_field(body, field)
    if not isinstance(value, bool):
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be a boolean" % field)
    return value


def req_int(body, field, min_v=None):
    value = req_field(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be an integer" % field)
    if min_v is not None and value < min_v:
        raise ApiError(ERR_VALIDATION, 400,
                       "field '%s' must be >= %s" % (field, min_v))
    return value


def req_num(body, field, gt=None, gte=None):
    value = req_field(body, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be a number" % field)
    if gt is not None and not value > gt:
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be > %s" % (field, gt))
    if gte is not None and not value >= gte:
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be >= %s" % (field, gte))
    return value


def req_enum(body, field, allowed):
    value = req_field(body, field)
    if value not in allowed:
        raise ApiError(ERR_VALIDATION, 400,
                       "field '%s' must be one of %s" % (field, list(allowed)))
    return value


def req_list(body, field):
    value = req_field(body, field)
    if not isinstance(value, list):
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be an array" % field)
    return value


def opt_num(body, field):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be a number" % field)
    return value


def opt_str(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "field '%s' must be a string" % field)
    return value


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, 400, "limit and offset must be integers")
    if limit < 1:
        raise ApiError(ERR_VALIDATION, 400, "limit must be >= 1")
    if offset < 0:
        raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    if limit > 100:
        limit = 100
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    return value if value not in (None, "") else None


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return None


def by_created(items):
    """Default list ordering: created_at ascending (insertion order tie-break)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
