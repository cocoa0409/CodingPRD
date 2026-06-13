"""Shared helpers: time parsing, pagination, body validation, serialization."""
import re
from datetime import datetime, timezone, timedelta

from flask import request

from errors import err, ERR_VALIDATION_LIMIT, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Time / clock
# ---------------------------------------------------------------------------
ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"
)
MMDD_RE = re.compile(r"^\d{2}-\d{2}$")


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime. Raises
    ERR_INVALID_REQUEST on malformed input. Returns None for None."""
    if value is None:
        return None
    if not isinstance(value, str) or not ISO_RE.match(value):
        raise err(ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp: %r" % value)
    s = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(dt, months):
    """Add a whole number of months to an aware datetime, clamping day overflow."""
    month0 = dt.month - 1 + months
    year = dt.year + month0 // 12
    month = month0 % 12 + 1
    # clamp day to the last valid day of the target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def validate_mmdd(value):
    if not isinstance(value, str) or not MMDD_RE.match(value):
        raise err(ERR_INVALID_REQUEST, "birth_month_day must be MM-DD")
    mm, dd = value.split("-")
    m, d = int(mm), int(dd)
    if not (1 <= m <= 12) or not (1 <= d <= 31):
        raise err(ERR_INVALID_REQUEST, "birth_month_day out of range")
    return value


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict (empty dict when absent)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def require_str(body, name):
    require_fields(body, name)
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_number(body, name):
    require_fields(body, name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    return v


def require_int(body, name):
    require_fields(body, name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def opt_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Return (limit, offset). Out-of-bounds -> ERR_VALIDATION_LIMIT (422)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION_LIMIT, "limit must be in [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "offset must be an integer")
        if offset < 0:
            raise err(ERR_VALIDATION_LIMIT, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created-order (_seq), slice by limit/offset, build pagination meta.

    `items` must already be filtered. Default ordering is created_at ASC
    (PRD §2.3); _seq is the stable proxy for created_at ASC.
    """
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination
