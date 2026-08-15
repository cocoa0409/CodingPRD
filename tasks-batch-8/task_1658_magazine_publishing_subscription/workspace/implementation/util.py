"""Shared helpers: timestamps, response envelope, pagination, rounding."""

import math
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from db import store
from errors import err

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def month_end_instant(year, month):
    """Last millisecond of the given calendar month (UTC)."""
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return nxt - timedelta(milliseconds=1)


def months_between(earlier, later):
    """Whole calendar months between two datetimes (later - earlier)."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


# ---------------------------------------------------------------------------
# Rounding (PRD 2.8)
# ---------------------------------------------------------------------------


def round_half_up_cents(value):
    """Round a Decimal/int/float to whole cents, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope (scaffold response_envelope / PRD 2.2)
# ---------------------------------------------------------------------------


def make_meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(store.now()),
    }


def success(data, code=200, pagination=None):
    meta = make_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_body(api_error):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, range [1,100]; offset default 0, >=0
# ---------------------------------------------------------------------------


def paginate(items):
    """Slice an already-sorted list; returns (page, pagination-meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION_PARAMETERS", "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise err(
            "ERR_INVALID_PAGINATION_PARAMETERS",
            "limit must be within [1, 100] and offset must be >= 0",
        )
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_creation(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Request body / field validation (priority 17 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def req_string(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return value


def req_int(data, field, minimum=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return value


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum=minimum)


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return data[field]


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return data[field]


def req_enum(data, field, allowed):
    value = data.get(field)
    if value not in allowed:
        raise err(
            "ERR_INVALID_REQUEST",
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return value


def opt_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def req_datetime(data, field):
    value = parse_iso(data.get(field))
    if value is None:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime")
    return value


_US_POSTAL_RE = re.compile(r"^\d{5}(-\d{4})?$")


def postal_code_valid(country_code, postal_code):
    """USPS-style validity: enforced for US addresses; foreign codes pass."""
    if country_code != "US":
        return True
    return bool(_US_POSTAL_RE.match(postal_code or ""))


def weight_ceil(excess):
    """ceil() of a possibly-float ounce excess, per postal-rate formula."""
    return int(math.ceil(Decimal(str(excess))))
