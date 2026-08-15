"""Core infrastructure: in-memory store, logical clock, errors, envelope, auth, parsing."""
import uuid
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from fractions import Fraction

from flask import request, jsonify


# ---------------------------------------------------------------------------
# In-memory store (no persistence; fresh on every process boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.insertion_orders = {}
        self.line_items = {}
        self.creatives = {}
        self.snapshots = {}
        self.events = {}
        self.verification_reports = {}
        self.make_goods = {}
        self.reconciliations = {}
        self.wrap_reports = {}
        self.seq = 0
        # Logical clock: startup default 2026-08-01T00:00:00Z, never wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def now_dt():
    return db.clock


def today():
    return db.clock.date()


ROLES = {"AdOpsManager", "Trafficker", "VerificationAnalyst", "BillingManager"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


def err_unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_stale_version(msg="expected_line_item_version does not match current LineItem.version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="Resource not in a valid from-state for the requested action"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_fraud_hold(msg="Line item is under a fraud hold"):
    return ApiError("ERR_FRAUD_HOLD", msg, 409)


def err_flight_window(msg="Line item start_date/end_date outside parent IO flight"):
    return ApiError("ERR_FLIGHT_WINDOW_VIOLATION", msg, 422)


def err_flight_not_started(msg="Current date outside line item flight window"):
    return ApiError("ERR_FLIGHT_NOT_STARTED", msg, 422)


def err_snapshot_out_of_flight(msg="snapshot_date outside line item flight"):
    return ApiError("ERR_SNAPSHOT_OUT_OF_FLIGHT", msg, 422)


def err_recon_overlap(msg="Reconciliation period overlaps an existing reconciliation of the same line item"):
    return ApiError("ERR_RECONCILIATION_OVERLAP", msg, 409)


def err_verification_overlap(msg="Verification report period overlaps an existing report for the same line item and vendor"):
    return ApiError("ERR_VERIFICATION_PERIOD_OVERLAP", msg, 409)


def err_no_tagged_creative(msg="Line item has no TAGGED creative"):
    return ApiError("ERR_NO_TAGGED_CREATIVE", msg, 409)


def err_io_not_approved(msg="Parent insertion order is not APPROVED or ACTIVE"):
    return ApiError("ERR_IO_NOT_APPROVED", msg, 409)


def err_line_item_not_live(msg="Parent line item is not LIVE"):
    return ApiError("ERR_LINE_ITEM_NOT_LIVE", msg, 409)


def err_no_breach(msg="Report is not a BREACH or is not OPEN"):
    return ApiError("ERR_NO_BREACH", msg, 409)


def err_recon_not_locked(msg="A reconciliation of the order's line items is not LOCKED"):
    return ApiError("ERR_RECONCILIATION_NOT_LOCKED", msg, 409)


def err_unresolved_make_goods(msg="A related make-good is still PROPOSED or APPROVED"):
    return ApiError("ERR_UNRESOLVED_MAKE_GOODS", msg, 409)


def err_sod(msg="Segregation of duties violated"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_duplicate_snapshot(msg="A delivery snapshot already exists for this line item and date"):
    return ApiError("ERR_DUPLICATE_SNAPSHOT", msg, 409)


def err_frequency_cap(msg="Frequency cap exceeded for this user"):
    return ApiError("ERR_FREQUENCY_CAP_EXCEEDED", msg, 422)


def err_tag_required(msg="TAG requires non-empty ad_tag; FAIL_QA requires non-empty qa_failure_reason"):
    return ApiError("ERR_TAG_REQUIRED", msg, 400)


def err_budget_exceeded(msg="Sum of non-CANCELLED line-item budgets would exceed IO.total_budget_cents"):
    return ApiError("ERR_BUDGET_EXCEEDED", msg, 422)


def err_credit_exceeds(msg="CREDIT make-good exceeds the report's make_good_max_credit_cents"):
    return ApiError("ERR_CREDIT_EXCEEDS_BASIS", msg, 422)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def render_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def render_instant(dt):
    """ISO 8601 UTC instant; fractional milliseconds only when nonzero."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def envelope_ok(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": render_ts(now_dt()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def envelope_error(error_id, message, status):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": render_ts(now_dt()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_role(*roles):
    uid, role = auth_user()
    if role not in roles:
        raise err_forbidden()
    return uid, role


ANY_ROLE = ("AdOpsManager", "Trafficker", "VerificationAnalyst", "BillingManager")


# ---------------------------------------------------------------------------
# Body / field parsing helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' is required and must be a string" % name)
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' must be a string" % name)
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if not is_int(v):
        raise err_invalid_request("Field '%s' is required and must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err_invalid_request("Field '%s' must be >= %d" % (name, minimum))
    return v


def opt_int(body, name, minimum=None, allow_null=False, default=None):
    if name not in body or body.get(name) is None:
        if allow_null and name in body and body.get(name) is None:
            return None
        return default
    v = body.get(name)
    if not is_int(v):
        raise err_invalid_request("Field '%s' must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err_invalid_request("Field '%s' must be >= %d" % (name, minimum))
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def req_decimal(body, name, lo=None, hi=None):
    v = body.get(name)
    if not is_num(v):
        raise err_invalid_request("Field '%s' is required and must be a number" % name)
    d = Decimal(str(v))
    if lo is not None and d < lo:
        raise err_invalid_request("Field '%s' out of range" % name)
    if hi is not None and d > hi:
        raise err_invalid_request("Field '%s' out of range" % name)
    return v, d


def opt_decimal(body, name, lo=None, hi=None, default_raw=None, default_dec=None):
    if name not in body or body.get(name) is None:
        return default_raw, default_dec
    return req_decimal(body, name, lo=lo, hi=hi)


def parse_date_value(v, field):
    """Parse an ISO date (or datetime) into a date object."""
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' must be an ISO date string" % field)
    s = v.strip()
    try:
        if "T" in s or " " in s:
            dt = parse_dt_value(s, field)
            return dt.date()
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        raise err_invalid_request("Field '%s' is not a valid ISO date" % field)


def req_date(body, name):
    if name not in body or body.get(name) is None:
        raise err_invalid_request("Field '%s' is required" % name)
    raw = body.get(name)
    return raw, parse_date_value(raw, name)


def parse_dt_value(v, field):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' must be an ISO 8601 datetime string" % field)
    s = v.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err_invalid_request("Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(body, name):
    if name not in body or body.get(name) is None:
        raise err_invalid_request("Field '%s' is required" % name)
    raw = body.get(name)
    return raw, parse_dt_value(raw, name)


def opt_dt(body, name):
    if name not in body or body.get(name) is None:
        return None, None
    raw = body.get(name)
    return raw, parse_dt_value(raw, name)


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def rhu_int(numer, denom):
    """round_half_up(numer / denom) to an integer."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate4(numer, denom):
    """round_half_up(numer / denom) to 4 decimal places, as Decimal."""
    return (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ceil_dec(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Pagination / sorting
# ---------------------------------------------------------------------------
def sorted_items(items):
    return sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))


def paginate(items):
    """items: already-sorted list of public views. Returns a Flask response."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return envelope_ok(page, status=200, response_type="array", pagination=pagination)


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Common fields for primary resources: id/created_at/updated_at/version."""
    rec["id"] = new_id()
    rec["_created_dt"] = now_dt()
    rec["_updated_dt"] = now_dt()
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_ledger(rec):
    """Ledger records (snapshots, events): id/created_at only."""
    rec["id"] = new_id()
    rec["_created_dt"] = now_dt()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["version"] += 1
    rec["_updated_dt"] = now_dt()
