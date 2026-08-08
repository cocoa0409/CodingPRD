"""Cross-cutting helpers: errors, response envelope, auth, validation, math, dates."""
import re
import random
import string
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from store import store


ROLES = {
    "PlatformAdmin", "Recruiter", "CredentialingSpecialist",
    "Clinician", "FacilityManager", "PayrollAdmin",
}

READ_ROLES = ["Recruiter", "CredentialingSpecialist", "PayrollAdmin",
              "PlatformAdmin", "Clinician", "FacilityManager"]


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": store.now_ts()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    pg = {"limit": limit, "offset": offset, "total_count": total,
          "has_more": (offset + limit) < total}
    return ok(items, 200, "array", pg)


def error_response(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or not role.strip() or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


TRANSITION_ROLE_MAP = {
    "contract": {
        "SENT_FOR_SIGNATURE": {"Recruiter"},
        "COUNTERSIGN_REQUESTED": {"Clinician"},
        "FULLY_EXECUTED": {"Clinician"},
    },
    "packet": {
        "SUBMITTED": {"Clinician", "CredentialingSpecialist"},
        "UNDER_REVIEW": {"CredentialingSpecialist"},
        "CHANGES_REQUESTED": {"CredentialingSpecialist"},
        "CLEARED": {"CredentialingSpecialist"},
        "REJECTED": {"CredentialingSpecialist"},
    },
    "timesheet": {
        "APPROVED": {"FacilityManager"},
        "DISPUTED": {"FacilityManager"},
        "SUBMITTED": {"Clinician"},
        "VOIDED": {"PayrollAdmin"},
    },
}


def fine_authz(kind, role, to):
    """Per-transition role restriction (ERR_UNAUTHORIZED) for user-drivable targets."""
    m = TRANSITION_ROLE_MAP[kind]
    if isinstance(to, str) and to in m and role not in m[to]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted to drive this transition")


def check_ownership(role, uid, assignment):
    """Ownership for entity-backed roles against an assignment."""
    if role == "Clinician" and assignment["clinician_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Clinician does not own this resource")
    if role == "FacilityManager" and assignment["facility_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Facility does not own this resource")


# ---------------------------------------------------------------------------
# Body / query parsing & validation (ERR_VALIDATION)
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return b


def verr(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(b, key, allow_empty=False):
    if key not in b:
        verr("Missing required field: %s" % key)
    v = b[key]
    if not isinstance(v, str):
        verr("Field %s must be a string" % key)
    if not allow_empty and v == "":
        verr("Field %s must not be empty" % key)
    return v


def opt_str(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str):
        verr("Field %s must be a string" % key)
    return v


def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        verr("Field %s must be one of %s" % (key, sorted(allowed)))
    return v


def opt_enum(b, key, allowed, default):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str) or v not in allowed:
        verr("Field %s must be one of %s" % (key, sorted(allowed)))
    return v


def req_int(b, key):
    if key not in b:
        verr("Missing required field: %s" % key)
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Field %s must be an integer" % key)
    return v


def opt_bool(b, key, default=False):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, bool):
        verr("Field %s must be a boolean" % key)
    return v


STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_state_code(b, key):
    v = req_str(b, key)
    if not STATE_CODE_RE.match(v):
        verr("Field %s must be exactly 2 uppercase letters" % key)
    return v


def parse_date(s, key="date"):
    if not isinstance(s, str) or not DATE_RE.match(s):
        verr("Field %s must be a YYYY-MM-DD date" % key)
    try:
        return date.fromisoformat(s)
    except ValueError:
        verr("Field %s must be a valid calendar date" % key)


def req_date(b, key):
    v = req_str(b, key)
    parse_date(v, key)
    return v


def opt_date(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    parse_date(v, key)
    return v


def req_sunday(b, key):
    v = req_date(b, key)
    if parse_date(v, key).weekday() != 6:
        verr("Field %s must be a Sunday" % key)
    return v


def req_hours_number(b, key):
    if key not in b:
        verr("Missing required field: %s" % key)
    return coerce_hours(b[key], key)


def coerce_hours(v, key):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr("Field %s must be a number" % key)
    d = Decimal(str(v))
    if d < 0:
        verr("Field %s must be non-negative" % key)
    return d


# Pagination & filters
def pagination():
    args = request.args
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            verr("limit must be an integer")
        if limit < 1 or limit > 100:
            verr("limit must be between 1 and 100")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            verr("offset must be an integer")
        if offset < 0:
            verr("offset must be non-negative")
    return limit, offset


def paginate(rows, limit, offset):
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------
def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def round_half_up(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(a, b):
    a = int(a)
    b = int(b)
    if a <= 0:
        return 0
    return (a + b - 1) // b


def pct_4dp(numer, denom):
    if denom == 0:
        return Decimal("0")
    return (D(numer) / D(denom)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num(x):
    """Serialize a Decimal/number: integral -> int, else float."""
    if isinstance(x, Decimal):
        if x == x.to_integral_value():
            return int(x)
        return float(x)
    return x


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def days_between(a_str, b_str):
    return (date.fromisoformat(b_str) - date.fromisoformat(a_str)).days


def add_days(d_str, n):
    return (date.fromisoformat(d_str) + timedelta(days=n)).isoformat()


def date_le(a, b):
    return date.fromisoformat(a) <= date.fromisoformat(b)


def date_lt(a, b):
    return date.fromisoformat(a) < date.fromisoformat(b)


# ---------------------------------------------------------------------------
# Common entity field management
# ---------------------------------------------------------------------------
def new_common(extra_common=True):
    ts = store.now_ts()
    base = {"id": None, "created_at": ts, "_seq": store.next_seq()}
    if extra_common:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    entity["updated_at"] = store.now_ts()
    entity["version"] += 1
