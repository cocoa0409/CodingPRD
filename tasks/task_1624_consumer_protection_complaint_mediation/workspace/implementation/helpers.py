"""Foundation helpers: errors, response envelope, auth, field validation,
datetime formatting, money rounding, pagination, record plumbing."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from store import db

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status), per PRD section 5 / SCAFFOLD errors
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_AMOUNT": 400,
    "ERR_CONSUMER_NOT_FOUND": 404,
    "ERR_BUSINESS_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_MEDIATOR_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_RESPONSE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_COMPLAINT": 409,
    "ERR_UNIQUENESS_VIOLATION": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_MEDIATOR_TIME_CONFLICT": 409,
    "ERR_ROOM_TIME_CONFLICT": 409,
    "ERR_MEDIATOR_CASELOAD_FULL": 409,
    "ERR_DUPLICATE_ACTIVE_ALERT": 409,
    "ERR_FILING_WINDOW_EXPIRED": 422,
    "ERR_NO_JURISDICTION": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_PATTERN_REFERRAL_REQUIRED": 422,
    "ERR_MEDIATOR_CONFLICT_OF_INTEREST": 422,
    "ERR_REFERENCED_ENTITY_INACTIVE": 422,
    "ERR_RESUBMISSION_CAP_REACHED": 422,
    "ERR_APPEAL_ALREADY_USED": 422,
    "ERR_SESSION_IN_PAST": 422,
    "ERR_COOLING_OFF_ACTIVE": 422,
    "ERR_RESCISSION_WINDOW_EXPIRED": 422,
    "ERR_BREACH_NOT_DUE": 422,
    "ERR_RESTITUTION_EXCEEDS_OUTSTANDING": 422,
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
# Timestamp formatting (PRD sections 2.2 / 2.4 / 2.6)
# ---------------------------------------------------------------------------

def fmt_dt3(dt):
    """ISO 8601 UTC with exactly three fractional digits (common fields)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Logical-clock stamp rendering: bare seconds when sub-second is zero."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_dt3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt3(db.now),
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
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth (PRD section 2.1; validation priorities 1-2)
# ---------------------------------------------------------------------------

ALL_ROLES = {
    "Anonymous",
    "Consumer",
    "Business",
    "IntakeOfficer",
    "Mediator",
    "EnforcementAttorney",
    "UnitDirector",
}


def auth(*allowed_roles):
    """Validate identity headers, then role permission. Returns X-User-ID."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        fail(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
        )
    if allowed_roles and role not in allowed_roles:
        fail("ERR_FORBIDDEN", "Role %s is not permitted for this endpoint" % role)
    return uid


def caller_role():
    return request.headers.get("X-User-Role")


def check_complaint_party(complaint, uid, role):
    """Priority-3 ownership for party roles on complaint-scoped resources.
    Staff roles (opaque identifiers) are never ownership-checked."""
    if role == "Consumer" and complaint["consumer_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Consumer callers act only on their own complaints")
    if role == "Business" and complaint["business_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Business callers act only on complaints against them")


def complaint_visible_to(complaint, uid, role):
    """Read scoping predicate for list endpoints (no error raised)."""
    if role == "Consumer":
        return complaint["consumer_id"] == uid
    if role == "Business":
        return complaint["business_id"] == uid
    return True


# ---------------------------------------------------------------------------
# Request body / field validation (validation priority 5)
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


def opt_string(data, name):
    v = data.get(name)
    if v is not None and not isinstance(v, str):
        _invalid("%s must be a string" % name)
    return v


def req_enum(data, name, domain):
    v = data.get(name)
    if v not in domain:
        _invalid("%s must be one of %s" % (name, sorted(domain)))
    return v


def opt_enum(data, name, domain, default=None):
    v = data.get(name)
    if v is None:
        return default
    if v not in domain:
        _invalid("%s must be one of %s" % (name, sorted(domain)))
    return v


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s is required and must be an integer" % name)
    return v


def opt_int(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s must be an integer" % name)
    return v


def opt_bool(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        _invalid("%s must be a boolean" % name)
    return v


def opt_string_list(data, name, default=None):
    v = data.get(name)
    if v is None:
        return default
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _invalid("%s must be an array of strings" % name)
    return v


def parse_date(s, name="incident_date"):
    if not isinstance(s, str):
        _invalid("%s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        _invalid("%s must be an ISO date (YYYY-MM-DD)" % name)


def req_date(data, name):
    v = data.get(name)
    if v is None:
        _invalid("%s is required and must be an ISO date (YYYY-MM-DD)" % name)
    return parse_date(v, name)


def parse_datetime_iso(s, name="timestamp"):
    if not isinstance(s, str):
        _invalid("%s must be an ISO 8601 timestamp" % name)
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _invalid("%s must be an ISO 8601 timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, name):
    v = data.get(name)
    if v is None:
        _invalid("%s is required and must be an ISO 8601 timestamp" % name)
    return parse_datetime_iso(v, name)


# ---------------------------------------------------------------------------
# Money / numeric rounding (PRD section 2.9)
# ---------------------------------------------------------------------------

def round_half_up_int(value):
    """Round a Decimal to an integer, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    """Creation order (created_at ascending, stable over insertion order),
    then limit/offset. Returns (page, total, limit, offset)."""
    items = sorted(items, key=lambda r: r["created_at"])
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


# ---------------------------------------------------------------------------
# Record plumbing (PRD section 2.4)
# ---------------------------------------------------------------------------

def new_record():
    now = db.now
    return {"id": str(uuid.uuid4()), "created_at": now, "updated_at": now, "version": 1}


def touch(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["updated_at"] = db.now
    rec["version"] += 1


def set_fields(rec, **changes):
    """Assign fields; touch the record only if a value actually changed."""
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed
