"""Shared helpers: envelope, errors, clock, ids, math."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(),
    }


def success_object(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = make_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    """Logical clock. Never falls back to wall-clock."""

    def __init__(self):
        self._now = EPOCH

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = Clock()


def iso_now():
    return format_iso(CLOCK.now())


def format_iso(dt):
    """ISO 8601 UTC with exactly 3 fractional digits, trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 with Z or offset. Return aware datetime UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------
def round_half_up(value, places=0):
    """Round half-up to the given number of decimal places.

    Returns an int when places == 0 else a float with exact decimal value.
    """
    q = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(d)
    return float(d)


def ceil_div_to_int(x):
    """Ceiling of x to an integer (x may be float)."""
    d = Decimal(str(x))
    return int(d.to_integral_value(rounding="ROUND_CEILING"))


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------
def get_json_body():
    from flask import request
    if not request.is_json:
        err("ERR_VALIDATION", 400, "Request body must be JSON")
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        err("ERR_VALIDATION", 400, "Request body is not valid JSON")
    if body is None or not isinstance(body, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def require(body, field, kind=None):
    if field not in body:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = body[field]
    if kind == "string":
        if not isinstance(v, str):
            err("ERR_VALIDATION", 400, f"Field {field} must be a string")
    elif kind == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    elif kind == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            err("ERR_VALIDATION", 400, f"Field {field} must be a number")
    elif kind == "bool":
        if not isinstance(v, bool):
            err("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def optional(body, field, default=None, kind=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if kind == "string" and not isinstance(v, str):
        err("ERR_VALIDATION", 400, f"Field {field} must be a string")
    elif kind == "int" and (isinstance(v, bool) or not isinstance(v, int)):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    elif kind == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
        err("ERR_VALIDATION", 400, f"Field {field} must be a number")
    elif kind == "bool" and not isinstance(v, bool):
        err("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def require_enum(body, field, values):
    v = require(body, field, "string")
    if v not in values:
        err("ERR_VALIDATION", 400, f"Field {field} must be one of {sorted(values)}")
    return v


def optional_enum(body, field, values, default=None):
    v = optional(body, field, default, "string")
    if v is None:
        return None
    if v not in values:
        err("ERR_VALIDATION", 400, f"Field {field} must be one of {sorted(values)}")
    return v


def require_positive_number(body, field, allow_zero=False):
    v = require(body, field, "number")
    if allow_zero:
        if v < 0:
            err("ERR_VALIDATION", 400, f"Field {field} must be >= 0")
    else:
        if v <= 0:
            err("ERR_VALIDATION", 400, f"Field {field} must be > 0")
    return v


def require_nonnegative_number(body, field):
    return require_positive_number(body, field, allow_zero=True)


def require_nonnegative_int(body, field):
    v = require(body, field, "int")
    if v < 0:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= 0")
    return v


def require_positive_int(body, field):
    v = require(body, field, "int")
    if v <= 0:
        err("ERR_VALIDATION", 400, f"Field {field} must be > 0")
    return v


def parse_pagination():
    from flask import request
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset
