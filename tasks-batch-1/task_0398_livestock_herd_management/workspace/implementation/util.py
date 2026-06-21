"""Shared helpers: type-checked field extraction, date/datetime parsing,
decimal rounding, and pagination parsing.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import errors
from clock import clock


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_json_body():
    """Parse the request body as JSON regardless of the Content-Type header.

    Action endpoints frequently send an empty body; treat that as {}. A present
    but non-JSON / non-object body is ERR_INVALID_REQUEST."""
    import json as _json
    from flask import request

    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    # try Flask's JSON parse first (honors Content-Type), then force-parse raw
    body = request.get_json(silent=True)
    if body is None:
        try:
            body = _json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise errors.invalid_request("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_present(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    return body[field]


def as_str(body, field, required=True, min_len=None, max_len=None, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise errors.invalid_request("Field %s must be a string" % field)
    if min_len is not None and len(v) < min_len:
        raise errors.invalid_request("Field %s too short" % field)
    if max_len is not None and len(v) > max_len:
        raise errors.invalid_request("Field %s too long" % field)
    return v


def as_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_number(body, field, required=True, default=None,
              gt=None, ge=None, le=None, lt=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    v = body[field]
    if not _is_number(v):
        raise errors.invalid_request("Field %s must be a number" % field)
    if gt is not None and not (v > gt):
        raise errors.invalid_request("Field %s must be > %s" % (field, gt))
    if ge is not None and not (v >= ge):
        raise errors.invalid_request("Field %s must be >= %s" % (field, ge))
    if lt is not None and not (v < lt):
        raise errors.invalid_request("Field %s must be < %s" % (field, lt))
    if le is not None and not (v <= le):
        raise errors.invalid_request("Field %s must be <= %s" % (field, le))
    return v


def as_int(body, field, required=True, default=None, ge=None, le=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request("Field %s must be an integer" % field)
    if ge is not None and v < ge:
        raise errors.invalid_request("Field %s must be >= %s" % (field, ge))
    if le is not None and v > le:
        raise errors.invalid_request("Field %s must be <= %s" % (field, le))
    return v


# --------------------------------------------------------------------------
# Date / datetime parsing  (all date comparisons are at date granularity, UTC)
# --------------------------------------------------------------------------
def parse_datetime(value, field):
    """Parse an ISO 8601 datetime or date string into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request("Field %s must be an ISO 8601 string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # try plain date
        try:
            d = date.fromisoformat(value.strip())
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            raise errors.invalid_request("Field %s is not a valid ISO 8601 value" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_date(value, field):
    """Return a datetime.date (UTC) from an ISO date or datetime string."""
    return parse_datetime(value, field).date()


def date_field(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    return parse_date(body[field], field)


def datetime_field(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    return parse_datetime(body[field], field)


def iso_date(d):
    """Serialize a datetime.date as an ISO date string, or pass through None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def iso_datetime(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


# --------------------------------------------------------------------------
# Rounding (round-half-up; never float for money)
# --------------------------------------------------------------------------
def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # 10^-places
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    return float(r)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, [1,100]; offset default 0, >= 0.
# Out-of-range -> ERR_VALIDATION_LIMIT.
# --------------------------------------------------------------------------
def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_limit()
        if limit < 1 or limit > 100:
            raise errors.validation_limit()

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_limit()
        if offset < 0:
            raise errors.validation_limit()

    return limit, offset


def paginate(sorted_items, limit, offset):
    total = len(sorted_items)
    window = sorted_items[offset:offset + limit]
    return window, total
