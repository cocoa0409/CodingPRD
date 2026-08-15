"""Shared utilities: errors, response envelope, logical clock, validation."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _wall_ts():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ok_object(data, status=200):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _wall_ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _wall_ts()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    """Serialize an aware datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_dt(value, field):
    """Parse an ISO-8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO-8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} is not a parseable datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(numer, denom):
    """Round half up of numer/denom to an integer."""
    return int((Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Auth context
# ---------------------------------------------------------------------------

ROLES = {"TeamAdmin", "TeamLeader", "Agent", "ReferralPartner"}


def auth_context():
    """Priority 1: headers present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID header missing or malformed")
    if not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-Role header missing or malformed")
    return uid.strip(), role


def require_role(role, allowed):
    """Priority 2: caller role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       f"Role {role} is not permitted on this endpoint")


# ---------------------------------------------------------------------------
# Body validation (strict schema)
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON object body; {} when absent. Reject non-object bodies."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def check_allowed(body, allowed):
    for key in body:
        if key not in allowed:
            raise err_invalid_request(f"Undeclared field: {key}")


def req_field(body, field):
    if field not in body or body[field] is None:
        raise err_invalid_request(f"Missing required field: {field}")
    return body[field]


def opt_field(body, field, default=None):
    if field not in body:
        return default
    return body[field]


def as_str(value, field):
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be a string")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field} must be an integer")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return value


def as_enum(value, field, values):
    if not isinstance(value, str) or value not in values:
        raise err_invalid_request(f"{field} must be one of {sorted(values)}")
    return value


def parse_pagination():
    """limit: default 10, 1..100; offset: default 0, >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def month_key(dt, tzname):
    """Calendar month key of dt in the given IANA timezone (UTC fallback)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzname)
    except Exception:
        tz = timezone.utc
    local = dt.astimezone(tz)
    return (local.year, local.month)


DAY = timedelta(days=1)
