"""Core plumbing: constants, in-memory store, logical clock, envelope, auth."""
import random
import string
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request

UTC = timezone.utc

app = Flask(__name__)
app.url_map.strict_slashes = False

# --------------------------------------------------------------------------
# Constants (SCAFFOLD.yaml / PRD.md)
# --------------------------------------------------------------------------
ROLES = {
    "PlatformAdmin", "HRPartner", "HRReviewer", "HRDirector", "PayrollSpecialist",
    "ITOperator", "ITVerifier", "ITManager", "Manager", "AssetClerk",
    "BenefitsAdministrator",
}
CASE_TYPES = {"RESIGNATION", "TERMINATION", "MUTUAL_SEPARATION", "JOB_ABANDONMENT"}
RESIGNATION_TYPES = {"RESIGNATION", "MUTUAL_SEPARATION"}
TERMINATION_TYPES = {"TERMINATION", "JOB_ABANDONMENT"}
STATE_CODES = {"CA", "CO", "IL", "MA", "TX", "NY", "WA", "FL"}
SYSTEM_NAMES = {"EMAIL", "VPN", "ERP", "CODE_REPO", "BADGE", "PAYROLL_SYSTEM", "CRM", "CLOUD_STORAGE"}
ASSET_KINDS = {"LAPTOP", "MONITOR", "PHONE", "KEYCARD", "TOOLING", "VEHICLE", "UNIFORM", "OTHER"}
RETURN_CONDITIONS = {"GOOD", "NORMAL_WEAR", "DAMAGED", "DESTROYED"}
NOTICE_KINDS = {"COBRA_ELECTION", "BENEFITS_TERMINATION", "RETIREMENT_PLAN", "LIFE_INSURANCE_CONVERSION"}
COVENANT_KINDS = {"NON_COMPETE", "NON_SOLICIT_CLIENTS", "NON_SOLICIT_EMPLOYEES", "CONFIDENTIALITY", "IP_ASSIGNMENT"}
REHIRE_CODES = {"ELIGIBLE", "ELIGIBLE_WITH_CONDITIONS", "INELIGIBLE"}

NOTICE_CAP_DAYS = 30
PTO_PAYOUT_STATES = {"CA", "CO", "IL", "MA"}
CALENDAR_DAY_STATES = {"CA", "CO", "MA"}
BUSINESS_DAY_STATES = {"IL", "NY", "WA"}
NEXT_PAYDAY_STATES = {"TX", "FL"}
RESIGNATION_NOTICE_THRESHOLD_HOURS = 72

DEP_BPS_BY_KIND = {"LAPTOP": 20, "PHONE": 25}
DEP_BPS_DEFAULT = 10
MAX_DEPRECIATION_BPS = 7000
DAMAGE_FRACTION_DAMAGED = "0.5"  # DESTROYED = full replacement cost
LATE_FEE_CENTS = 2500
ASSET_RETURN_GRACE_DAYS = 3
ASSET_DEFAULT_GRACE_DAYS = 7

WAITING_TIME_CAP_DAYS = 30
HOURS_PER_DAY = 8

REVOKE_OFFSET_HOURS = {
    "EMAIL": 0, "VPN": 0, "CRM": 0,
    "ERP": 24, "PAYROLL_SYSTEM": 24,
    "CODE_REPO": -24, "CLOUD_STORAGE": -24,
    "BADGE": 1,
}
MAX_REVOKE_RETRIES = 3
RETRY_BACKOFF_MINUTES = 60

MAX_INTERVIEW_RESCHEDULES = 2
INTERVIEW_HARD_LIMIT_DAYS = 5

BENEFITS_DEADLINE_DAYS = {
    "COBRA_ELECTION": 44,
    "BENEFITS_TERMINATION": 30,
    "RETIREMENT_PLAN": 30,
    "LIFE_INSURANCE_CONVERSION": 31,
}
COVENANT_REMIND_DAYS = 3
MAX_NOTICE_FAILURES = 2
DEDUPE_WINDOW_MINUTES = 60

DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# In-memory store (starts empty on every boot — no seeding)
# --------------------------------------------------------------------------
DB = {
    "cases": {},
    "tasks": {},
    "notifications": [],   # append-only
    "assets": {},
    "statements": {},
    "interviews": {},
    "plans": {},
    "sessions": {},
    "notices": {},
    "acks": {},
    "reviews": {},
}
_SEQ = [0]
LOCK = threading.RLock()

# Logical clock: datetime + raw string as provided by the last set call.
CLOCK = {
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC),
    "raw": DEFAULT_CLOCK_RAW,
}


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def now_dt():
    return CLOCK["dt"]


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 timestamp to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_timestamp():
    """api_request_timestamp: server wall clock, ISO 8601 UTC, 3 fractional digits."""
    return fmt_dt(datetime.now(UTC))


# --------------------------------------------------------------------------
# Errors and response envelope
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role is not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Resource is not in a state that allows this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_case_terminal(msg="Operation against a CLOSED or VOIDED case"):
    return ApiError("ERR_CASE_TERMINAL", 409, msg)


def err_sod(msg="Segregation-of-duties violation"):
    return ApiError("ERR_SOD_VIOLATION", 422, msg)


def err_temporal(msg="Temporal sanity violation"):
    return ApiError("ERR_TEMPORAL_INVALID", 422, msg)


def err_referential(msg="Referential integrity violation"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", 422, msg)


def err_overlap(msg="Schedule window overlaps an existing scheduled window"):
    return ApiError("ERR_SCHEDULE_OVERLAP", 422, msg)


def err_retry_cap(msg="Retry/reschedule/requeue cap reached"):
    return ApiError("ERR_RETRY_CAP_EXCEEDED", 422, msg)


def err_sequence_gate(msg="Revocation ordering gate not satisfied"):
    return ApiError("ERR_SEQUENCE_GATE", 422, msg)


def err_fiscal(msg="Fiscal input out of range"):
    return ApiError("ERR_FISCAL_INVALID", 422, msg)


def err_deadline(msg="Legal deadline protection triggered"):
    return ApiError("ERR_DEADLINE_MISSED", 422, msg)


def err_bad_request(msg="Invalid request payload"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": wall_timestamp(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Validate identity headers and endpoint role permission (priorities 1-2)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    if role not in allowed_roles:
        raise err_forbidden()
    g.user_id = uid
    g.user_role = role


# --------------------------------------------------------------------------
# Field helpers
# --------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err_bad_request("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err_bad_request("Request body must be a JSON object")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        raise err_bad_request("%s is required and must be a non-empty string" % name)
    return v


def new_record():
    t = now_dt()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = now_dt()


def ser(rec):
    """Serialize a record: drop internal keys, format datetimes."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def paginate(records):
    """Sort by created_at ascending (insertion order tiebreak) and paginate."""
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ser(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Request lifecycle: serialize all requests through one lock; error envelope
# --------------------------------------------------------------------------
@app.before_request
def _acquire_lock():
    LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    LOCK.release()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(err_not_found())


@app.errorhandler(405)
def _handle_405(e):
    return error_response(err_not_found("Resource or method not found"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", 500, "Internal server error"))
