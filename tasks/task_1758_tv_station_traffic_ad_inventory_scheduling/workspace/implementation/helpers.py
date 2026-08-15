"""Foundation: error catalog, response envelope, auth, field validation,
dates, and pagination — all named exactly per SCAFFOLD.yaml §1.0/§1.4 and
PRD §2."""

import re
import uuid
from datetime import date, datetime, timezone

from flask import jsonify, request

from store import db

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status), per SCAFFOLD §1.6 / PRD §5
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DATE_WINDOW": 422,
    "ERR_REFERENCE_MISMATCH": 422,
    "ERR_POLITICAL_RESERVE": 422,
    "ERR_AVAIL_OVERFLOW": 422,
    "ERR_SEPARATION_VIOLATION": 422,
    "ERR_COPY_NOT_RECEIVED": 422,
    "ERR_RECONCILE_MISMATCH": 422,
    "ERR_CREDIT_LIMIT": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_AVAIL_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.status = ERROR_STATUS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Logical-clock rendering: seconds precision when whole, else 3 digits."""
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(db.now),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(page, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1; validation priorities 1-2)
# ---------------------------------------------------------------------------

ALL_ROLES = {
    "SalesRep",
    "TrafficManager",
    "CopyCoordinator",
    "BillingClerk",
    "StationAdmin",
}


def auth(*allowed_roles):
    """Priority 1: headers present and role recognized -> ERR_UNAUTHENTICATED.
    Priority 2: role in the endpoint's authorized list -> ERR_FORBIDDEN."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        fail(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must "
            "be one of the five declared roles",
        )
    if allowed_roles and role not in allowed_roles:
        fail("ERR_FORBIDDEN", "Role %s is not authorized for this endpoint" % role)
    return uid


# ---------------------------------------------------------------------------
# Request body and field-level validation (validation priority 13)
# ---------------------------------------------------------------------------

def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _invalid(msg):
    fail("ERR_INVALID_REQUEST", msg)


def req_string(data, name):
    v = data.get(name)
    if v is None or not isinstance(v, str) or v == "":
        _invalid("%s is required and must be a non-empty string" % name)
    return v


def opt_string(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        _invalid("%s must be a string" % name)
    return v


def req_enum(data, name, domain):
    v = data.get(name)
    if v not in domain:
        _invalid("%s must be one of %s" % (name, sorted(domain)))
    return v


def req_int(data, name, min_value=None, max_value=None, domain=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s is required and must be an integer" % name)
    if domain is not None and v not in domain:
        _invalid("%s must be one of %s" % (name, sorted(domain)))
    if min_value is not None and v < min_value:
        _invalid("%s must be at least %s" % (name, min_value))
    if max_value is not None and v > max_value:
        _invalid("%s must be at most %s" % (name, max_value))
    return v


def opt_int(data, name, default=None, min_value=None, max_value=None):
    v = data.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s must be an integer" % name)
    if min_value is not None and v < min_value:
        _invalid("%s must be at least %s" % (name, min_value))
    if max_value is not None and v > max_value:
        _invalid("%s must be at most %s" % (name, max_value))
    return v


def req_number(data, name, min_value=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid("%s is required and must be a number" % name)
    if min_value is not None and v < min_value:
        _invalid("%s must be at least %s" % (name, min_value))
    return v


def opt_bool(data, name, default=False):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        _invalid("%s must be a boolean" % name)
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_iso_date(value, name="date"):
    """Strict YYYY-MM-DD parse; returns a datetime.date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        _invalid("%s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        _invalid("%s must be an ISO date (YYYY-MM-DD)" % name)


def req_date_str(data, name):
    """Validate an ISO date body field; returns the canonical string form."""
    return parse_iso_date(data.get(name), name).isoformat()


def req_time_hhmm(data, name):
    v = data.get(name)
    if not isinstance(v, str) or not _TIME_RE.match(v):
        _invalid("%s must be a local 24-hour HH:MM string" % name)
    return v


def parse_iso_datetime(value, name="to_iso8601"):
    if not isinstance(value, str):
        _invalid("%s must be an ISO 8601 timestamp" % name)
    t = value
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _invalid("%s must be an ISO 8601 timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def opt_version_field(data, name):
    """OCC guard field: integer when present, else None (presence is enforced
    by the endpoint where the field is non-optional, PRD §2.8)."""
    v = data.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s must be an integer" % name)
    return v


# ---------------------------------------------------------------------------
# Record plumbing (PRD §2.4)
# ---------------------------------------------------------------------------

def new_record():
    now = db.now
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Every mutation — primary or cascaded side effect — refreshes
    updated_at and increments version (PRD §2.4)."""
    rec["updated_at"] = db.now
    rec["version"] += 1


def created_key(rec):
    """Creation order: created_at ASC with insertion sequence as the fixed
    tie-break (the spot id is never consulted, PRD §3.5)."""
    return (rec["created_at"], rec["_seq"])


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    """Sort by creation timestamp ascending and apply limit/offset.
    Returns (page, total, limit, offset)."""
    items = sorted(items, key=created_key)
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    return items[offset : offset + limit], total, limit, offset


def list_response(items, serializer):
    page, total, limit, offset = paginate(items)
    return ok_list([serializer(r) for r in page], total, limit, offset)


def query_filter(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def query_int_filter(name):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        _invalid("%s must be an integer" % name)
