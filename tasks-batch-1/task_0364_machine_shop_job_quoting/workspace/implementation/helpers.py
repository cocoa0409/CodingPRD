"""Validation, serialization, pagination, rounding, and date helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------


def round_half_up(value):
    """Round a numeric value to the nearest integer, half away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round to 2 decimal places, half away from zero; return float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------


def get_body():
    """Return the JSON body as a dict (empty dict when none/empty)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def validate_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))


def as_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, maximum))
    return val


def as_number(body, field, required=True, default=None, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return val


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime; raise ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_date(dt):
    return dt.date()


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_pagination():
    """Read limit/offset from query string with defaults and clamping."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None or limit == "":
        limit_val = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_val < PAGINATION_MIN_LIMIT:
            limit_val = PAGINATION_MIN_LIMIT
        elif limit_val > PAGINATION_MAX_LIMIT:
            limit_val = PAGINATION_MAX_LIMIT

    if offset is None or offset == "":
        offset_val = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_val = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_val < 0:
            offset_val = 0

    return limit_val, offset_val


def paginate(items):
    """Sort by created_at ASC (tie-break insertion seq) and page."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    limit, offset = get_pagination()
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Serialization — strip internal fields
# ---------------------------------------------------------------------------


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_list(items):
    return [serialize(r) for r in items]
