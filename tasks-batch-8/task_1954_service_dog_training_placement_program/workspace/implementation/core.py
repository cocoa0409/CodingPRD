"""Core infrastructure: in-memory store, logical clock, envelope, errors, validation, auth."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# ---------------------------------------------------------------------------
# In-memory store (fresh on every process boot; no seeding)
# ---------------------------------------------------------------------------
STORE = {
    "applicants": {},
    "assessments": {},
    "waitlist_entries": {},
    "contributions": {},
    "puppy_raisers": {},
    "trainers": {},
    "dogs": {},
    "screenings": {},
    "placements": {},
    "milestones": {},
    "matches": {},
    "classes": {},
    "enrollments": {},
    "pats": {},
    "partnerships": {},
    "followups": {},
    "recerts": {},
    "support_requests": {},
}

_SEQ = [0]

# Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall-clock.
CLOCK = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]

ROLES = {
    "ProgramAdmin",
    "IntakeCoordinator",
    "TrainingDirector",
    "Veterinarian",
    "Trainer",
    "Evaluator",
    "Applicant",
    "PuppyRaiser",
}

TERMINAL_STATES = {
    "applicants": {"DENIED", "WITHDRAWN"},
    "waitlist_entries": {"CLOSED"},
    "contributions": {"REFUNDED", "VOID"},
    "puppy_raisers": {"INACTIVE"},
    "trainers": {"INACTIVE"},
    "dogs": {"CAREER_CHANGED", "RETIRED"},
    "screenings": {"CLEARED", "FAILED"},
    "matches": {"REJECTED", "DISSOLVED", "COMPLETED"},
    "classes": {"COMPLETED", "CANCELLED"},
    "enrollments": {"GRADUATED", "FAILED", "WITHDRAWN"},
    "pats": {"SCORED_PASS", "SCORED_FAIL", "INVALIDATED"},
    "partnerships": {"RETIRED", "DISSOLVED"},
    "followups": {"COMPLETED", "MISSED", "WAIVED"},
    "recerts": {"COMPLETED_PASS", "FAILED_FINAL"},
    "support_requests": {"CLOSED"},
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_validation(msg="Request body is malformed or fails validation"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_ownership(msg="Actor may only operate on its own records"):
    return ApiError("ERR_OWNERSHIP_SCOPE", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_ref_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def err_already_terminal(msg="Resource is in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def err_invalid_state(msg="Resource is not in a valid state for this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now():
    return CLOCK[0]


def today():
    return CLOCK[0].date()


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def wall_ts():
    return fmt_ts(datetime.now(timezone.utc))


def parse_datetime_val(s):
    """Parse ISO-8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date_val(s):
    """Parse strict YYYY-MM-DD date; returns date or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_fields():
    _SEQ[0] += 1
    t = now()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": _SEQ[0],
    }


def milestone_base_fields():
    _SEQ[0] += 1
    t = now()
    return {"id": new_id(), "created_at": t, "_seq": _SEQ[0]}


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now()


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=22)
        ),
        "api_request_timestamp": wall_ts(),
    }
    if pagination:
        m.update(pagination)
    return m


def respond(data, code=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": data}),
        code,
    )


def respond_list(items, total, limit, offset):
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return (
        jsonify(
            {"meta": _meta(pg), "response_type": "array", "data": items}
        ),
        200,
    )


def respond_error(err):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.status,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def actor():
    """Validate auth headers; returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise err_unauthenticated()
    return role, uid


def require_roles(*roles):
    role, uid = actor()
    if role not in roles:
        raise err_forbidden()
    return role, uid


# ---------------------------------------------------------------------------
# Request body / field validation
# ---------------------------------------------------------------------------
def body():
    """Parse JSON object body. Empty body -> {}. Malformed -> ERR_VALIDATION."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    b = request.get_json(silent=True)
    if b is None or not isinstance(b, dict):
        raise err_validation("Request body must be a JSON object")
    return b


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def v_str(b, key, required=True):
    val = b.get(key)
    if val is None:
        if required:
            raise err_validation("Missing required field: %s" % key)
        return None
    if not isinstance(val, str) or len(val) == 0:
        raise err_validation("Field %s must be a non-empty string" % key)
    return val


def v_int(b, key, required=True, min_v=None, max_v=None):
    val = b.get(key)
    if val is None:
        if required:
            raise err_validation("Missing required field: %s" % key)
        return None
    if not _is_int(val):
        raise err_validation("Field %s must be an integer" % key)
    if min_v is not None and val < min_v:
        raise err_validation("Field %s below minimum" % key)
    if max_v is not None and val > max_v:
        raise err_validation("Field %s above maximum" % key)
    return val


def v_bool(b, key, default=None):
    val = b.get(key)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise err_validation("Field %s must be a boolean" % key)
    return val


def v_enum(b, key, members, required=True):
    val = b.get(key)
    if val is None:
        if required:
            raise err_validation("Missing required field: %s" % key)
        return None
    if not isinstance(val, str) or val not in members:
        raise err_validation("Field %s has an invalid value" % key)
    return val


def v_date(b, key, required=True):
    val = b.get(key)
    if val is None:
        if required:
            raise err_validation("Missing required field: %s" % key)
        return None
    d = parse_date_val(val)
    if d is None:
        raise err_validation("Field %s must be an ISO date (YYYY-MM-DD)" % key)
    return d


def v_datetime(b, key, required=True):
    val = b.get(key)
    if val is None:
        if required:
            raise err_validation("Missing required field: %s" % key)
        return None
    d = parse_datetime_val(val)
    if d is None:
        raise err_validation("Field %s must be an ISO 8601 datetime" % key)
    return d


def v_str_array(b, key, members=None, min_len=None, required=True):
    val = b.get(key)
    if val is None:
        if required:
            raise err_validation("Missing required field: %s" % key)
        return None
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise err_validation("Field %s must be an array of strings" % key)
    if min_len is not None and len(val) < min_len:
        raise err_validation("Field %s requires at least %d entries" % (key, min_len))
    if members is not None:
        for x in val:
            if x not in members:
                raise err_validation("Field %s has an invalid member" % key)
    return val


def pagination_params():
    """Parse and validate limit/offset query params."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err_validation("limit must be an integer")
        if str(limit_raw).strip() != str(limit):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err_validation("offset must be an integer")
        if str(offset_raw).strip() != str(offset):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, serializer=None):
    """Sort by creation order, apply pagination, respond."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset : offset + limit]
    if serializer:
        page = [serializer(e) for e in page]
    return respond_list(page, total, limit, offset)


def list_all(coll, serializer):
    """Non-paginated sub-resource list (created_at ASC via insertion seq)."""
    ordered = sorted(coll, key=lambda e: e["_seq"])
    data = [serializer(e) for e in ordered]
    return (
        jsonify({"meta": _meta(), "response_type": "array", "data": data}),
        200,
    )


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def round_half_up_1dp(value):
    """value may be Decimal/float/int -> float rounded half-up to 1dp."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Resource resolution helpers
# ---------------------------------------------------------------------------
def get_or_404(coll_name, rid):
    e = STORE[coll_name].get(rid)
    if e is None:
        raise err_not_found("Resource %s not found" % rid)
    return e


def check_terminal(coll_name, entity, status_field="status"):
    terminal = TERMINAL_STATES.get(coll_name, set())
    if entity.get(status_field) in terminal:
        raise err_already_terminal(
            "%s is in terminal state %s" % (coll_name, entity.get(status_field))
        )
