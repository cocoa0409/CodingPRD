"""In-memory store, response envelope, auth, validation helpers, clock, calculations."""
import random
import string
import uuid
from datetime import datetime, timezone, date, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

ROLES = {"CareCoordinator", "Caregiver", "FamilyContact", "BillingClerk"}

# ---------------------------------------------------------------------------
# In-memory store (fresh on every process start; NO seeding)
# ---------------------------------------------------------------------------
store = {
    "clients": {},
    "family_contacts": {},
    "caregivers": {},
    "background_checks": {},
    "bonds": {},
    "schedules": {},
    "visits": {},
    "assignments": {},
    "addons": {},
    "invoices": {},
    "ltc_policies": {},
    "claims": {},
    "wellness_checks": {},
    "visit_logs": {},
}
_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def clock():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_wall():
    return datetime.now(UTC)


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse ISO 8601 (with 'Z' or offset) or a bare date. Returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    v = s.strip()
    if not v:
        return None
    try:
        raw = v.replace("Z", "+00:00") if v.endswith("Z") else v
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass
    try:
        d = date.fromisoformat(v)
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Decimal / money helpers
# ---------------------------------------------------------------------------
def D(v):
    return Decimal(str(v))


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_dt(now_wall())}
    if pagination:
        m.update(pagination)
    return m


def ok(data, response_type="object", code=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), code


def ok_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID or X-User-Role header")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------
def get_or_404(collection, _id):
    rec = store[collection].get(_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Common record fields / mutation
# ---------------------------------------------------------------------------
def new_record(with_status=None):
    ts = now_wall()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    if with_status is not None:
        rec["status"] = with_status
    return rec


def touch(rec):
    rec["updated_at"] = now_wall()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
def body_json():
    return request.get_json(silent=True) or {}


def _type_ok(val, t):
    if t == "str":
        return isinstance(val, str)
    if t == "int":
        return isinstance(val, int) and not isinstance(val, bool)
    if t == "num":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if t == "datetime":
        return parse_dt(val) is not None
    return False


def validate_required(body, spec):
    """spec: list of (field, type). Raises ERR_INVALID_REQUEST."""
    for field, t in spec:
        if field not in body or body[field] is None:
            raise ApiError("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}")
        if not _type_ok(body[field], t):
            raise ApiError("ERR_INVALID_REQUEST", 422, f"Invalid type for field: {field}")


def validate_optional(body, spec):
    for field, t in spec:
        if field in body and body[field] is not None:
            if not _type_ok(body[field], t):
                raise ApiError("ERR_INVALID_REQUEST", 422, f"Invalid type for field: {field}")


def validate_enum(body, field, allowed):
    val = body.get(field)
    if val is not None and val not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"Invalid enum value for {field}: {val}")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items already sorted; returns (page, pagination_meta)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def sorted_by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Derived / effective status
# ---------------------------------------------------------------------------
def bgcheck_status(bc):
    if bc["status"] == "CLEARED" and bc.get("expires_at") is not None and clock() >= bc["expires_at"]:
        return "EXPIRED"
    return bc["status"]


def bond_status(bond):
    if clock() >= bond["expiry_date"]:
        return "LAPSED"
    return "ACTIVE"


def schedule_status(s):
    if s["status"] == "ACTIVE" and clock() > s["end_date"]:
        return "ENDED"
    return s["status"]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def labor_charge_raw(actual_minutes, hourly_rate_cents, ot_threshold_hours, ot_multiplier, min_visit_minutes):
    billable_minutes = max(D(actual_minutes), D(min_visit_minutes))
    billable_hours = billable_minutes / D(60)
    ott = D(ot_threshold_hours)
    regular_hours = min(billable_hours, ott)
    ot_hours = billable_hours - ott
    if ot_hours < 0:
        ot_hours = D(0)
    raw = regular_hours * D(hourly_rate_cents) + ot_hours * D(hourly_rate_cents) * D(ot_multiplier)
    return raw


def minutes_between(start, end):
    return (end - start).total_seconds() / 60.0


def visit_scheduled_minutes(v):
    return int(round(minutes_between(v["scheduled_start"], v["scheduled_end"])))


# ---------------------------------------------------------------------------
# Computed-field reconciliation (each recompute touches the owner if changed)
# ---------------------------------------------------------------------------
def recompute_client_balance(client):
    cid = client["id"]
    finalized = sum(
        inv["total_cents"] for inv in store["invoices"].values()
        if inv["client_id"] == cid and inv["status"] == "FINALIZED"
    )
    approved = 0
    for cl in store["claims"].values():
        if cl["status"] != "APPROVED":
            continue
        inv = store["invoices"].get(cl["invoice_id"])
        if inv is not None and inv["client_id"] == cid:
            approved += cl["reimbursed_cents"]
    val = finalized - approved
    if client["outstanding_balance_cents"] != val:
        client["outstanding_balance_cents"] = val
        touch(client)


def recompute_committed_minutes(caregiver):
    total = 0
    for a in store["assignments"].values():
        if a["caregiver_id"] == caregiver["id"] and a["status"] == "CONFIRMED":
            v = store["visits"].get(a["visit_id"])
            if v is not None:
                total += visit_scheduled_minutes(v)
    if caregiver["committed_minutes"] != total:
        caregiver["committed_minutes"] = total
        touch(caregiver)


def recompute_policy(policy):
    total = sum(
        cl["reimbursed_cents"] for cl in store["claims"].values()
        if cl["ltc_policy_id"] == policy["id"] and cl["status"] == "APPROVED"
    )
    changed = False
    if policy["reimbursed_to_date_cents"] != total:
        policy["reimbursed_to_date_cents"] = total
        changed = True
    # EXHAUSTED is terminal/sticky once reached.
    if policy["status"] != "EXHAUSTED" and total >= policy["lifetime_max_cents"]:
        policy["status"] = "EXHAUSTED"
        changed = True
    if changed:
        touch(policy)
