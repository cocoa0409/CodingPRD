"""Shared utilities: parsing, rounding, pagination, request access."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err
import clock


# ----------------------------------------------------------------------------
# Rounding
# ----------------------------------------------------------------------------
def round_half_up_int(value):
    """Round a numeric/Decimal to the nearest integer, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dp(value, places):
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> Decimal('0.01')
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


# ----------------------------------------------------------------------------
# Datetime parsing
# ----------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 string into a tz-aware UTC datetime, or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Invalid datetime value.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Request body / query access
# ----------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


# ----------------------------------------------------------------------------
# Pagination
# ----------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit out of range.")

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc, then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return page, total


def now():
    return clock.now()
