"""Time, parsing, request-shape, and pagination helpers."""
import re
from datetime import datetime, timezone

from flask import request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Logical clock / formatting
# --------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_dt():
    return store.clock


def now_iso():
    return fmt_ts(store.clock)


def today():
    return store.clock.date()


def minute_of_day():
    return store.clock.hour * 60 + store.clock.minute


def parse_datetime(value):
    """Parse a full ISO 8601 instant with timezone; None when invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date; None when invalid."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def term_end_string(year):
    return "{}-12-31T23:59:59Z".format(year)


def parse_term_end(s):
    return datetime(int(s[0:4]), 12, 31, 23, 59, 59, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Request body / field shape
# --------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid required field: {}".format(field))
    return v


def opt_string(body, field, default=None):
    if field not in body:
        return default
    v = body[field]
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field {} must be a string or null".format(field))
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field {} must be one of {}".format(field, sorted(allowed)))
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field {} must be a boolean".format(field))
    return v


def req_int(body, field):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field {} must be an integer".format(field))
    return v


# --------------------------------------------------------------------------
# Pagination (limit/offset; defaults 10/0, bounds 1..100 / >=0)
# --------------------------------------------------------------------------

def parse_pagination():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def slice_page(items, limit, offset):
    """Sort by created_at ascending (insertion order tiebreak) and slice."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def paginate(items):
    """Validate query params, sort, and slice in one step."""
    limit, offset = parse_pagination()
    return slice_page(items, limit, offset)
