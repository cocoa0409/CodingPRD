"""Core infrastructure: in-memory store, logical clock, envelope, errors, auth, helpers."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request, jsonify


# ----------------------------- errors -----------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ----------------------------- logical clock ----------------------

class _Clock:
    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = _Clock()


# ----------------------------- in-memory store --------------------
# Module-level dicts; a fresh process starts completely empty.

db = {
    "cases": {},
    "assessments": {},
    "quotes": {},
    "quote_line_items": {},
    "funding_sources": {},
    "funding_allocations": {},
    "installation_jobs": {},
    "rental_ramps": {},
    "inventory_units": {},
    "inspections": {},
    "invoices": {},
    "invoice_line_items": {},
    "warranty_claims": {},
    "ot_consultations": {},
    "reassessment_schedules": {},
}

_seq = [0]          # global monotonic insertion counter (tie-breaks created_at sort)
_counters = {}      # per (kind, yyyymmdd) counters for human-readable numbers


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def next_number(kind):
    """Human-readable sequence number, e.g. ('Q', '20260501') -> 1, 2, 3..."""
    day = CLOCK.now().strftime("%Y%m%d")
    key = (kind, day)
    _counters[key] = _counters.get(key, 0) + 1
    return day, _counters[key]


# ----------------------------- timestamps -------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime/date string into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    return CLOCK.now()


def now_iso():
    return iso(CLOCK.now())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ----------------------------- response envelope ------------------

def ok_object(data, status=200):
    body = {
        "meta": {"api_request_id": request_id(), "api_request_timestamp": now_iso()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": {"api_request_id": request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ----------------------------- auth / RBAC ------------------------

VALID_ROLES = {
    "IntakeCoordinator",
    "Assessor",
    "ProjectManager",
    "FundingCoordinator",
    "CrewLead",
    "LogisticsCoordinator",
    "Inspector",
    "BillingCoordinator",
    "Client",
    "SystemAdmin",
}


def user_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT", 400,
                       "X-User-ID header is missing or invalid")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT", 400,
                       "X-User-Role header is missing or invalid")
    return uid, role


def require_roles(*roles):
    """Validate user context, then role permission. Any valid role when roles empty."""
    uid, role = user_context()
    if roles and role not in roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       f"Role {role} is not permitted to perform this operation")
    return uid, role


# ----------------------------- request body helpers ---------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _fail(field):
    raise ApiError("ERR_INVALID_REQUEST", 400,
                   f"Missing or invalid required field: {field}")


def req_field(b, field):
    if field not in b or b[field] is None:
        _fail(field)
    return b[field]


def req_str(b, field):
    v = req_field(b, field)
    if not isinstance(v, str) or not v.strip():
        _fail(field)
    return v


def opt_str(b, field, default=None):
    v = b.get(field, default)
    if v is not None and not isinstance(v, str):
        _fail(field)
    return v


def _to_decimal(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    if isinstance(v, str):
        try:
            return Decimal(v.strip())
        except InvalidOperation:
            return None
    return None


def req_int(b, field):
    v = req_field(b, field)
    d = _to_decimal(v)
    if d is None or d != d.to_integral_value():
        _fail(field)
    return int(d)


def opt_int(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    return req_int(b, field)


def req_num(b, field):
    """Numeric value, returned as Decimal."""
    v = req_field(b, field)
    d = _to_decimal(v)
    if d is None:
        _fail(field)
    return d


def opt_num(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    return req_num(b, field)


def opt_bool(b, field, default=None):
    v = b.get(field, default)
    if v is not None and not isinstance(v, bool):
        _fail(field)
    return v


def opt_array(b, field, default=None):
    v = b.get(field, default)
    if v is not None and not isinstance(v, list):
        _fail(field)
    return v


def req_array(b, field):
    v = req_field(b, field)
    if not isinstance(v, list):
        _fail(field)
    return v


def req_enum(b, field, allowed):
    v = req_str(b, field)
    if v not in allowed:
        _fail(field)
    return v


def opt_enum(b, field, allowed, default=None):
    if field not in b or b[field] is None:
        return default
    return req_enum(b, field, allowed)


def req_dt(b, field):
    v = req_field(b, field)
    dt = parse_dt(v)
    if dt is None:
        _fail(field)
    return dt


def opt_dt(b, field, default=None):
    if field not in b or b[field] is None:
        return default
    return req_dt(b, field)


def round_half_up_cents(d):
    """Round a Decimal to integer cents, half up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------- pagination -------------------------

def pagination_params():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (insertion order tie-break), paginate, respond."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["_created_dt"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(r) for r in page], total, limit, offset)


# ----------------------------- record plumbing --------------------

def new_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": iso(ts),
        "updated_at": iso(ts),
        "version": 1,
        "_created_dt": ts,
        "_seq": next_seq(),
    }


def touch(record):
    record["version"] = int(record.get("version", 1)) + 1
    record["updated_at"] = now_iso()


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ----------------------------- existence helpers ------------------

def get_case_or_404(case_id):
    case = db["cases"].get(case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case with given ID does not exist")
    return case


def get_child_or_404(collection, child_id, parent_key, parent_id, error_id, label):
    rec = db[collection].get(child_id)
    if rec is None or rec.get(parent_key) != parent_id:
        raise ApiError(error_id, 404, f"{label} with given ID does not exist")
    return rec


def get_unit_or_404(unit_id):
    unit = db["inventory_units"].get(unit_id)
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND", 404,
                       "Inventory unit with given ID does not exist")
    return unit


# ----------------------------- OCC --------------------------------

def check_expected_case_version(case, b):
    if "expected_case_version" not in b or b["expected_case_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Missing or invalid required field: expected_case_version")
    v = b["expected_case_version"]
    d = _to_decimal(v)
    if d is None or d != d.to_integral_value():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Missing or invalid required field: expected_case_version")
    if int(d) != case["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "Expected version does not match current resource version")


def require_case_active(case):
    if case["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_CASE_NOT_ACTIVE", 409,
                       "Case must be in an active state (not CANCELLED or CLOSED)")
