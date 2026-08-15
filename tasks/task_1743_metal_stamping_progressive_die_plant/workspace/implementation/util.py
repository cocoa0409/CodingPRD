"""Logical clock, timestamps, IDs, response envelope, parsing helpers."""
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from errors import ApiError, invalid_request

# Logical clock: starts at exactly 2026-08-01T00:00:00Z, never falls back to wall clock.
_LOGICAL_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _LOGICAL_NOW


def set_now(dt):
    global _LOGICAL_NOW
    _LOGICAL_NOW = dt


def iso_now():
    return format_ts(now())


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed if naive)."""
    if not isinstance(value, str):
        raise invalid_request(f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    # Normalize trailing Z
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise invalid_request(f"{field} is not a valid ISO 8601 datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def get_pagination():
    """Parse limit/offset query params with defaults limit=10, offset=0; min 1, max 100."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def get_body():
    """Return parsed JSON body as a dict (empty dict if no body). Reject non-dict bodies."""
    if request.content_length is None and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request(f"Missing required field: {f}")


def as_str(value, field, required=True, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise invalid_request(f"{field} is required")
    if not isinstance(value, str):
        raise invalid_request(f"{field} must be a string")
    if required and value == "":
        raise invalid_request(f"{field} must not be empty")
    return value


def as_int(value, field, minimum=None, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise invalid_request(f"{field} is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise invalid_request(f"{field} must be >= {minimum}")
    return value


def as_number(value, field, minimum=None, minimum_exclusive=False, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise invalid_request(f"{field} is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request(f"{field} must be a number")
    d = Decimal(str(value))
    if minimum is not None:
        md = Decimal(str(minimum))
        if minimum_exclusive:
            if d <= md:
                raise invalid_request(f"{field} must be > {minimum}")
        else:
            if d < md:
                raise invalid_request(f"{field} must be >= {minimum}")
    return d


def as_bool(value, field, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise invalid_request(f"{field} is required")
    if not isinstance(value, bool):
        raise invalid_request(f"{field} must be a boolean")
    return value


def as_enum(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        raise invalid_request(f"{field} must be one of {sorted(choices)}")
    return value


def round3(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round6(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num(d):
    """Serialize a Decimal to a JSON number (int if integral, else float with full precision)."""
    if not isinstance(d, Decimal):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def touch(entity, with_version=True):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = iso_now()
    if with_version:
        entity["version"] = entity.get("version", 0) + 1


def common_fields():
    ts = iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def ledger_fields():
    """Append-only ledger records carry only id and created_at."""
    return {
        "id": new_id(),
        "created_at": iso_now(),
    }
