"""Errors, response envelope, auth, and request-field validation helpers.

All structural names (headers, envelope fields, pagination params, error ids)
come straight from SCAFFOLD.yaml / PRD.md — nothing assumed.
"""
import re
import secrets
from datetime import datetime

from flask import request

import store

# ---------------------------------------------------------------------------
# Error catalog (id -> http status), verbatim from the scaffold error table.
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_BAD_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_FORBIDDEN": 403,
    "ERR_NOT_ORDER_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_LOG_POSTURE_BLOCKED": 409,
    "ERR_ORDER_NOT_ACTIVE": 409,
    "ERR_UNRESOLVED_DISCREPANCIES": 409,
    "ERR_NO_ACTIVE_CLOCK": 422,
    "ERR_TRADE_AGREEMENT_REQUIRED": 422,
    "ERR_TRADE_AGREEMENT_INACTIVE": 409,
    "ERR_TRADE_CREDIT_EXCEEDED": 402,
    "ERR_SONG_NOT_ACTIVE": 409,
    "ERR_CATEGORY_RETIRED": 409,
    "ERR_CLEARANCE_NOT_CLEARED": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_SPIN_SEPARATION_VIOLATION": 422,
    "ERR_ARTIST_SEPARATION_VIOLATION": 422,
    "ERR_CLEARANCE_WINDOW_VIOLATION": 422,
    "ERR_CONTRACT_WINDOW_VIOLATION": 422,
    "ERR_DAYPART_HOUR_MISMATCH": 422,
    "ERR_SPOT_OUTSIDE_FLIGHT": 422,
    "ERR_FLIGHT_WINDOW_INVALID": 422,
    "ERR_LOG_ALREADY_EXISTS": 409,
    "ERR_CLOCK_WEEKDAY_OVERLAP": 409,
    "ERR_RATE_WINDOW_OVERLAP": 409,
    "ERR_CLEARANCE_WINDOW_OVERLAP": 409,
    "ERR_CATEGORY_SPIN_CAP_EXCEEDED": 422,
    "ERR_DISCREPANCY_NOT_WAIVABLE": 422,
    "ERR_DAYPART_UNITS_EXHAUSTED": 422,
    "ERR_PREEMPTION_NOT_ALLOWED": 409,
    "ERR_HOUR_CAPACITY_EXCEEDED": 409,
    "ERR_NO_RATE_CARD": 422,
    "ERR_RATE_FLOOR_VIOLATION": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERROR_HTTP[error_id]


def err(error_id, message):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope: {"meta": {...}, "response_type": ..., "data": ...}
# ---------------------------------------------------------------------------
def _meta_base():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": store.now_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return body, status


def success_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return body, 200


def error_body(error_id, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, ERROR_HTTP[error_id]


# ---------------------------------------------------------------------------
# Auth: X-User-ID and X-User-Role headers; five known roles.
# ---------------------------------------------------------------------------
ROLES = {"ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
         "BillingAdmin"}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED",
            "X-User-Role or X-User-ID header missing, or role unknown")
    return user_id, role


def require_role(*allowed):
    user_id, role = authenticate()
    if role not in allowed:
        err("ERR_ROLE_FORBIDDEN",
            "Role not permitted for this endpoint per RBAC matrix")
    return user_id, role


# ---------------------------------------------------------------------------
# Request-body field validators (priority-0 ERR_BAD_REQUEST checks).
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WEEKDAY_SET = set(WEEKDAYS)

DAYPARTS = ["MORNING_DRIVE", "MIDDAY", "AFTERNOON_DRIVE", "EVENING",
            "OVERNIGHT"]
DAYPART_HOURS = {
    "MORNING_DRIVE": {5, 6, 7, 8},
    "MIDDAY": {9, 10, 11, 12, 13},
    "AFTERNOON_DRIVE": {15, 16, 17, 18},
    "EVENING": {19, 20, 21},
    "OVERNIGHT": {0, 1, 2, 3, 4},
}


def get_body():
    """Return the JSON request body as a dict, or raise ERR_BAD_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err("ERR_BAD_REQUEST", "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def req_present(body, field):
    if field not in body or body[field] is None:
        err("ERR_BAD_REQUEST", f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = req_present(body, field)
    if not isinstance(v, str) or v == "":
        err("ERR_BAD_REQUEST", f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        err("ERR_BAD_REQUEST", f"Field {field} must be a string")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = req_present(body, field)
    if not _is_int(v):
        err("ERR_BAD_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        err("ERR_BAD_REQUEST", f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        err("ERR_BAD_REQUEST", f"Field {field} above maximum {maximum}")
    return v


def opt_int(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not _is_int(v):
        err("ERR_BAD_REQUEST", f"Field {field} must be an integer")
    return v


def req_number(body, field, minimum=None, exclusive_minimum=False):
    v = req_present(body, field)
    if not _is_number(v):
        err("ERR_BAD_REQUEST", f"Field {field} must be a number")
    if minimum is not None:
        if exclusive_minimum and not v > minimum:
            err("ERR_BAD_REQUEST", f"Field {field} must be > {minimum}")
        if not exclusive_minimum and v < minimum:
            err("ERR_BAD_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def opt_number(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not _is_number(v):
        err("ERR_BAD_REQUEST", f"Field {field} must be a number")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        err("ERR_BAD_REQUEST", f"Field {field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if not isinstance(v, str) or v not in allowed:
        err("ERR_BAD_REQUEST",
            f"Field {field} must be one of {sorted(allowed)}")
    return v


def parse_date_str(v, field):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        err("ERR_BAD_REQUEST", f"Field {field} must be a YYYY-MM-DD date")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        err("ERR_BAD_REQUEST", f"Field {field} is not a valid calendar date")


def req_date(body, field):
    return parse_date_str(req_present(body, field), field)


def req_weekday_set(body, field):
    v = req_present(body, field)
    if not isinstance(v, list) or len(v) == 0:
        err("ERR_BAD_REQUEST", f"Field {field} must be a non-empty array")
    for m in v:
        if not isinstance(m, str) or m not in WEEKDAY_SET:
            err("ERR_BAD_REQUEST",
                f"Field {field} members must be drawn from MON..SUN")
    if len(set(v)) != len(v):
        err("ERR_BAD_REQUEST", f"Field {field} must not contain duplicates")
    return v


def weekday_of(date_obj):
    return WEEKDAYS[date_obj.weekday()]


def req_str_list(body, field):
    v = req_present(body, field)
    if not isinstance(v, list):
        err("ERR_BAD_REQUEST", f"Field {field} must be an array")
    for m in v:
        if not isinstance(m, str):
            err("ERR_BAD_REQUEST", f"Field {field} members must be strings")
    return v


def parse_iso8601(v):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(v, str) or not v:
        err("ERR_BAD_REQUEST", "Field to_iso8601 must be an ISO 8601 string")
    s = v
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        err("ERR_BAD_REQUEST", "Field to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        err("ERR_BAD_REQUEST", "Field to_iso8601 must carry a UTC offset or Z")
    from datetime import timezone as _tz
    return dt.astimezone(_tz.utc)


# ---------------------------------------------------------------------------
# Pagination (limit/offset with defaults 10/0, min 1, max 100).
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_BAD_REQUEST", "limit must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < 1 or limit > 100:
            err("ERR_BAD_REQUEST", "limit must be an integer between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_BAD_REQUEST", "offset must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            err("ERR_BAD_REQUEST", "offset must be a non-negative integer")
    return limit, offset


def paginate(records, serializer):
    """records: pre-filtered iterable of dicts with created_at/_seq."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
