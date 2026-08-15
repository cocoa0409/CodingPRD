"""Shared utilities: error type, response envelope, datetime handling, validators."""
import re
import uuid
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, http_status, message):
    return ApiError(error_id, message, http_status)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _now_timestamp():
    """ISO 8601 UTC with exactly three fractional digits, stamped from the
    logical clock — PRD §2.4: "The system never reads the wall clock"."""
    from store import DB
    dt = DB.clock_dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _new_request_id(),
            "api_request_timestamp": _now_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _new_request_id(),
            "api_request_timestamp": _now_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": {
            "api_request_id": _new_request_id(),
            "api_request_timestamp": _now_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime_value(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not _DT_RE.match(s):
        return None
    norm = s
    if norm.endswith("Z"):
        norm = norm[:-1] + "+00:00"
    # normalise offsets like +0000 -> +00:00
    if len(norm) >= 5 and (norm[-5] in "+-") and norm[-2] != ":":
        norm = norm[:-2] + ":" + norm[-2:]
    try:
        dt = datetime.fromisoformat(norm)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_value(value):
    """Parse an ISO YYYY-MM-DD date string to a date, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def fmt_clock(dt):
    """Render a logical-clock datetime: whole seconds when possible."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def day_start_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def trip_end_instant(end_date_str):
    """Midnight UTC on the day after end_date."""
    d = parse_date_value(end_date_str)
    return day_start_utc(d) + timedelta(days=1)


def trip_start_instant(start_date_str):
    d = parse_date_value(start_date_str)
    return day_start_utc(d)


# ---------------------------------------------------------------------------
# Decimal helpers (integer cents, ROUND_HALF_UP)
# ---------------------------------------------------------------------------

def round_half_up_cents(numerator, denominator):
    """round_half_up(numerator / denominator) to integer cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def round_half_up_value(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body validators
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    if not isinstance(body[field], str):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return body[field]


def opt_str(body, field, default=""):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return body[field]


def req_int(body, field, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    if not _is_int(body[field]):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    v = body[field]
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} below minimum {min_value}")
    if max_value is not None and v > max_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} above maximum {max_value}")
    return v


def opt_int(body, field, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return None
    if not _is_int(body[field]):
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    v = body[field]
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} below minimum {min_value}")
    if max_value is not None and v > max_value:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} above maximum {max_value}")
    return v


def req_enum(body, field, allowed):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err(
            "ERR_INVALID_ENUM",
            400,
            f"Field {field} must be one of {', '.join(allowed)}",
        )
    return v


def req_datetime(body, field):
    raw = req_str(body, field)
    dt = parse_datetime_value(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 datetime")
    return raw, dt


def req_date(body, field):
    raw = req_str(body, field)
    d = parse_date_value(raw)
    if d is None:
        raise err("ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO date (YYYY-MM-DD)")
    return raw, d
