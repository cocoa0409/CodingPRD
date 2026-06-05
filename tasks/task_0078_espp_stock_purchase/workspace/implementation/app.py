"""Employee Stock Purchase Plan (ESPP) Administration API.

Single-file Flask implementation. In-memory storage only; all state resets on
process restart. Designed to boot fast for per-test-server isolation.
"""

import os
import uuid
import random
import string
import calendar
from datetime import datetime, timezone, date

from flask import Flask, jsonify, request


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_ADMIN = "PlanAdministrator"
ROLE_OFFICER = "ComplianceOfficer"
ROLE_PARTICIPANT = "Participant"
VALID_ROLES = {ROLE_ADMIN, ROLE_OFFICER, ROLE_PARTICIPANT}
ALL_ROLES = VALID_ROLES


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, http_status, error_id, message=None):
        super().__init__(message or error_id)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message or error_id


def err(http_status, error_id, message=None):
    return ApiError(http_status, error_id, message)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.participants = {}
        self.plans = {}
        self.offering_periods = {}
        self.purchase_periods = {}
        self.enrollments = {}
        self.contributions = {}
        self.purchases = {}
        self.share_lots = {}
        self.dispositions = {}
        self.forms = {}
        self.accrual_ledgers = {}


store = Store()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def envelope_object(data):
    return {"meta": meta(), "response_type": "object", "data": data}


def envelope_array(items, limit, offset, total_count, has_more):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = has_more
    return {"meta": m, "response_type": "array", "data": items}


def envelope_error(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def common_init(rec):
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at on any mutation."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(s):
    """Parse an ISO date/datetime string into a date. Returns None on failure."""
    if not isinstance(s, str) or not s:
        return None
    txt = s.strip()
    candidate = txt
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(txt[:10])
    except ValueError:
        return None


def add_months(d, months):
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = d.day
    last = calendar.monthrange(year, month)[1]
    if day > last:
        day = last
    return date(year, month, day)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up_over_100(numerator_x100):
    """round_half_up(numerator_x100 / 100), where numerator_x100 == value * 100.

    Supports int or float numerator (discount_pct / fmv may be fractional).
    """
    if isinstance(numerator_x100, float) and not numerator_x100.is_integer():
        scaled = round(numerator_x100 * 1000)  # value * 100000
        return (scaled * 2 + 100000) // (2 * 100000)
    n = int(round(numerator_x100)) if isinstance(numerator_x100, float) else numerator_x100
    return (n * 2 + 100) // (2 * 100)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise err(401, "ERR_UNAUTHENTICATED",
                  "Missing or unrecognized X-User-ID / X-User-Role headers.")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(403, "ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint.")


# ---------------------------------------------------------------------------
# Body / field parsing
# ---------------------------------------------------------------------------

def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err(400, "ERR_VALIDATION", "Malformed JSON body.")
    if not isinstance(body, dict):
        raise err(400, "ERR_VALIDATION", "Body must be a JSON object.")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def require_str(body, field):
    v = body.get(field)
    if not is_str(v) or not v.strip():
        raise err(400, "ERR_VALIDATION", f"{field} is required and must be a non-empty string.")
    return v


def require_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise err(400, "ERR_VALIDATION", f"{field} is required and must be an integer.")
    return v


def require_number(body, field):
    v = body.get(field)
    if not is_number(v):
        raise err(400, "ERR_VALIDATION", f"{field} is required and must be a number.")
    return v


def require_date(body, field):
    v = body.get(field)
    if not is_str(v):
        raise err(400, "ERR_VALIDATION", f"{field} is required and must be a date string.")
    d = parse_date(v)
    if d is None:
        raise err(400, "ERR_VALIDATION", f"{field} must be a valid ISO date.")
    return v, d


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise err(400, "ERR_VALIDATION", "limit must be an integer.")
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise err(400, "ERR_VALIDATION", "offset must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, total, has_more


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_participant(p):
    return {
        "id": p["id"], "email": p["email"], "full_name": p["full_name"],
        "employee_id": p["employee_id"], "is_five_percent_owner": p["is_five_percent_owner"],
        "status": p["status"], "created_at": p["created_at"],
        "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"], "company_name": p["company_name"],
        "max_contribution_rate_pct": p["max_contribution_rate_pct"],
        "discount_pct": p["discount_pct"], "lookback_enabled": p["lookback_enabled"],
        "annual_purchase_limit_usd": p["annual_purchase_limit_usd"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_offering(o):
    return {
        "id": o["id"], "plan_id": o["plan_id"], "grant_date": o["grant_date"],
        "duration_months": o["duration_months"], "end_date": o["end_date"],
        "grant_date_fmv_cents": o["grant_date_fmv_cents"], "status": o["status"],
        "purchase_period_count": o["purchase_period_count"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }


def ser_purchase_period(pp):
    return {
        "id": pp["id"], "offering_period_id": pp["offering_period_id"],
        "sequence_index": pp["sequence_index"], "purchase_date": pp["purchase_date"],
        "purchase_date_fmv_cents": pp["purchase_date_fmv_cents"], "status": pp["status"],
        "certified_by_user_id": pp["certified_by_user_id"],
        "created_at": pp["created_at"], "updated_at": pp["updated_at"], "version": pp["version"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"], "participant_id": e["participant_id"],
        "offering_period_id": e["offering_period_id"],
        "contribution_rate_pct": e["contribution_rate_pct"], "status": e["status"],
        "accumulated_contribution_cents": e["accumulated_contribution_cents"],
        "refunded_contribution_cents": e["refunded_contribution_cents"],
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def ser_contribution(c):
    return {
        "id": c["id"], "enrollment_id": c["enrollment_id"], "pay_date": c["pay_date"],
        "gross_pay_cents": c["gross_pay_cents"], "amount_cents": c["amount_cents"],
        "status": c["status"], "created_at": c["created_at"],
    }


def ser_purchase(p):
    return {
        "id": p["id"], "enrollment_id": p["enrollment_id"],
        "purchase_period_id": p["purchase_period_id"],
        "price_per_share_cents": p["price_per_share_cents"],
        "shares_purchased": p["shares_purchased"], "spend_cents": p["spend_cents"],
        "residual_cents": p["residual_cents"],
        "grant_date_value_applied_cents": p["grant_date_value_applied_cents"],
        "status": p["status"], "created_at": p["created_at"],
        "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_share_lot(s):
    return {
        "id": s["id"], "purchase_id": s["purchase_id"], "participant_id": s["participant_id"],
        "shares_total": s["shares_total"], "shares_remaining": s["shares_remaining"],
        "grant_date": s["grant_date"], "purchase_date": s["purchase_date"],
        "status": s["status"], "created_at": s["created_at"],
        "updated_at": s["updated_at"], "version": s["version"],
    }


def ser_disposition(d):
    return {
        "id": d["id"], "share_lot_id": d["share_lot_id"], "participant_id": d["participant_id"],
        "sale_date": d["sale_date"], "shares_sold": d["shares_sold"],
        "sale_price_per_share_cents": d["sale_price_per_share_cents"],
        "disposition_type": d["disposition_type"],
        "ordinary_income_cents": d["ordinary_income_cents"],
        "capital_gain_cents": d["capital_gain_cents"],
        "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
    }


def ser_form(f):
    return {
        "id": f["id"], "purchase_id": f["purchase_id"], "participant_id": f["participant_id"],
        "box3_grant_date_fmv_cents": f["box3_grant_date_fmv_cents"],
        "box4_purchase_date_fmv_cents": f["box4_purchase_date_fmv_cents"],
        "box5_price_paid_cents": f["box5_price_paid_cents"], "box6_shares": f["box6_shares"],
        "tax_year": f["tax_year"], "issued_by_user_id": f["issued_by_user_id"],
        "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
    }


def ser_ledger(l):
    return {
        "id": l["id"], "participant_id": l["participant_id"],
        "calendar_year": l["calendar_year"],
        "accrued_grant_value_cents": l["accrued_grant_value_cents"],
        "remaining_capacity_cents": l["remaining_capacity_cents"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err(404, "ERR_NOT_FOUND", "Referenced resource does not exist.")
    return rec


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify(envelope_error(e.error_id, e.message)), e.http_status


@app.errorhandler(404)
def _handle_404(_e):
    return jsonify(envelope_error("ERR_NOT_FOUND", "Not found.")), 404


@app.errorhandler(405)
def _handle_405(_e):
    return jsonify(envelope_error("ERR_NOT_FOUND", "Method not allowed.")), 404


# ============================ Participants ============================

@app.post("/participants")
def create_participant():
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    employee_id = require_str(body, "employee_id")

    is_owner = body.get("is_five_percent_owner", False)
    if not isinstance(is_owner, bool):
        raise err(400, "ERR_VALIDATION", "is_five_percent_owner must be a boolean.")

    rec = {
        "id": new_id(), "email": email, "full_name": full_name,
        "employee_id": employee_id, "is_five_percent_owner": is_owner, "status": "ACTIVE",
    }
    common_init(rec)
    store.participants[rec["id"]] = rec
    return jsonify(envelope_object(ser_participant(rec))), 201


@app.get("/participants/<rid>")
def read_participant(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.participants, rid)
    if role == ROLE_PARTICIPANT and uid != rec["id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own record.")
    return jsonify(envelope_object(ser_participant(rec))), 200


@app.post("/participants/<rid>/terminate")
def terminate_participant(rid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    rec = get_or_404(store.participants, rid)
    rec["status"] = "TERMINATED"
    touch(rec)
    return jsonify(envelope_object(ser_participant(rec))), 200


# ============================ Plans ============================

@app.post("/plans")
def create_plan():
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    company_name = require_str(body, "company_name")

    max_rate = body.get("max_contribution_rate_pct", 15)
    if not is_number(max_rate):
        raise err(400, "ERR_VALIDATION", "max_contribution_rate_pct must be a number.")
    if not (0 < max_rate <= 15):
        raise err(400, "ERR_VALIDATION", "max_contribution_rate_pct must be in (0, 15].")

    discount = body.get("discount_pct", 15)
    if not is_number(discount):
        raise err(400, "ERR_VALIDATION", "discount_pct must be a number.")
    if not (0 <= discount <= 15):
        raise err(400, "ERR_VALIDATION", "discount_pct must be in [0, 15].")

    lookback = body.get("lookback_enabled", True)
    if not isinstance(lookback, bool):
        raise err(400, "ERR_VALIDATION", "lookback_enabled must be a boolean.")

    limit_usd = body.get("annual_purchase_limit_usd", 25000)
    if not is_int(limit_usd):
        raise err(400, "ERR_VALIDATION", "annual_purchase_limit_usd must be an integer.")
    if not (limit_usd > 0):
        raise err(400, "ERR_VALIDATION", "annual_purchase_limit_usd must be > 0.")

    rec = {
        "id": new_id(), "company_name": company_name,
        "max_contribution_rate_pct": max_rate, "discount_pct": discount,
        "lookback_enabled": lookback, "annual_purchase_limit_usd": limit_usd,
    }
    common_init(rec)
    store.plans[rec["id"]] = rec
    return jsonify(envelope_object(ser_plan(rec))), 201


@app.get("/plans/<rid>")
def read_plan(rid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.plans, rid)
    return jsonify(envelope_object(ser_plan(rec))), 200


@app.get("/plans/<rid>/offering-periods")
def list_offerings_under_plan(rid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    get_or_404(store.plans, rid)
    limit, offset = get_pagination()
    status = request.args.get("status")
    rows = [o for o in store.offering_periods.values() if o["plan_id"] == rid]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_offering(o) for o in page], limit, offset, total, has_more)), 200


# ============================ Offering periods ============================

@app.post("/offering-periods")
def create_offering():
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    plan_id = require_str(body, "plan_id")
    grant_date_raw, grant_d = require_date(body, "grant_date")
    duration = require_int(body, "duration_months")
    grant_fmv = require_int(body, "grant_date_fmv_cents")
    if not (grant_fmv > 0):
        raise err(400, "ERR_VALIDATION", "grant_date_fmv_cents must be > 0.")

    get_or_404(store.plans, plan_id)

    if not (6 <= duration <= 24):
        raise err(422, "ERR_OFFERING_DURATION", "duration_months must be within [6, 24].")

    end_d = add_months(grant_d, duration)
    rec = {
        "id": new_id(), "plan_id": plan_id, "grant_date": grant_date_raw,
        "duration_months": duration, "end_date": end_d.isoformat(),
        "grant_date_fmv_cents": grant_fmv, "status": "OPEN", "purchase_period_count": 0,
        "_grant_d": grant_d, "_end_d": end_d,
    }
    common_init(rec)
    store.offering_periods[rec["id"]] = rec
    return jsonify(envelope_object(ser_offering(rec))), 201


@app.get("/offering-periods/<rid>")
def read_offering(rid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.offering_periods, rid)
    return jsonify(envelope_object(ser_offering(rec))), 200


@app.post("/offering-periods/<rid>/close-enrollment")
def close_enrollment(rid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    o = get_or_404(store.offering_periods, rid)
    if o["status"] != "OPEN":
        raise err(409, "ERR_INVALID_STATE", "close-enrollment requires offering OPEN.")
    o["status"] = "ENROLLMENT_CLOSED"
    touch(o)
    return jsonify(envelope_object(ser_offering(o))), 200


@app.post("/offering-periods/<rid>/cancel")
def cancel_offering(rid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    o = get_or_404(store.offering_periods, rid)
    if o["status"] not in ("OPEN", "ENROLLMENT_CLOSED"):
        raise err(409, "ERR_INVALID_STATE", "Offering cannot be cancelled from its current state.")
    children = [pp for pp in store.purchase_periods.values() if pp["offering_period_id"] == rid]
    if any(pp["status"] == "PURCHASED" for pp in children):
        raise err(409, "ERR_INVALID_STATE", "Offering with a settled purchase cannot be cancelled.")

    o["status"] = "CANCELLED"
    touch(o)

    for e in store.enrollments.values():
        if e["offering_period_id"] != rid:
            continue
        if e["status"] in ("ENROLLED", "SUSPENDED"):
            _withdraw_enrollment(e)
    for pp in children:
        if pp["status"] in ("PENDING", "OPEN", "CERTIFIED"):
            pp["status"] = "CANCELLED"
            touch(pp)
    return jsonify(envelope_object(ser_offering(o))), 200


# ============================ Purchase periods ============================

@app.post("/offering-periods/<rid>/purchase-periods")
def create_purchase_period(rid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    o = get_or_404(store.offering_periods, rid)
    body = get_body()

    seq = require_int(body, "sequence_index")
    purchase_date_raw, purchase_d = require_date(body, "purchase_date")
    pd_fmv = require_int(body, "purchase_date_fmv_cents")
    if not (seq >= 1):
        raise err(400, "ERR_VALIDATION", "sequence_index must be >= 1.")
    if not (pd_fmv > 0):
        raise err(400, "ERR_VALIDATION", "purchase_date_fmv_cents must be > 0.")
    for pp in store.purchase_periods.values():
        if pp["offering_period_id"] == rid and pp["sequence_index"] == seq:
            raise err(400, "ERR_VALIDATION", "sequence_index must be unique within the offering.")

    if purchase_d < o["_grant_d"] or purchase_d > o["_end_d"]:
        raise err(422, "ERR_PURCHASE_DATE_OUT_OF_RANGE",
                  "purchase_date must fall within [grant_date, end_date].")

    rec = {
        "id": new_id(), "offering_period_id": rid, "sequence_index": seq,
        "purchase_date": purchase_date_raw, "purchase_date_fmv_cents": pd_fmv,
        "status": "PENDING", "certified_by_user_id": None, "_purchase_d": purchase_d,
    }
    common_init(rec)
    store.purchase_periods[rec["id"]] = rec

    o["purchase_period_count"] += 1
    touch(o)
    return jsonify(envelope_object(ser_purchase_period(rec))), 201


@app.get("/purchase-periods/<rid>")
def read_purchase_period(rid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.purchase_periods, rid)
    return jsonify(envelope_object(ser_purchase_period(rec))), 200


@app.get("/offering-periods/<rid>/purchase-periods")
def list_purchase_periods(rid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    get_or_404(store.offering_periods, rid)
    limit, offset = get_pagination()
    status = request.args.get("status")
    rows = [pp for pp in store.purchase_periods.values() if pp["offering_period_id"] == rid]
    if status is not None:
        rows = [pp for pp in rows if pp["status"] == status]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_purchase_period(pp) for pp in page], limit, offset, total, has_more)), 200


@app.post("/purchase-periods/<rid>/open")
def open_purchase_period(rid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    pp = get_or_404(store.purchase_periods, rid)
    o = store.offering_periods.get(pp["offering_period_id"])

    if pp["status"] != "PENDING":
        raise err(409, "ERR_INVALID_STATE", "open requires PurchasePeriod PENDING.")
    if o is None or o["status"] not in ("ENROLLMENT_CLOSED", "ACTIVE"):
        raise err(409, "ERR_INVALID_STATE", "parent offering must be ENROLLMENT_CLOSED or ACTIVE.")

    siblings = [s for s in store.purchase_periods.values()
                if s["offering_period_id"] == pp["offering_period_id"]
                and s["sequence_index"] < pp["sequence_index"]]
    if any(s["status"] not in ("PURCHASED", "CANCELLED") for s in siblings):
        raise err(409, "ERR_SEQUENCE_NOT_READY",
                  "lower sequence_index siblings must be PURCHASED/CANCELLED first.")

    pp["status"] = "OPEN"
    touch(pp)

    if o["status"] == "ENROLLMENT_CLOSED":
        o["status"] = "ACTIVE"
        touch(o)
    return jsonify(envelope_object(ser_purchase_period(pp))), 200


@app.post("/purchase-periods/<rid>/certify")
def certify_purchase_period(rid):
    uid, role = authenticate()
    require_role(role, {ROLE_OFFICER})
    pp = get_or_404(store.purchase_periods, rid)
    if pp["status"] != "OPEN":
        raise err(409, "ERR_INVALID_STATE", "certify requires PurchasePeriod OPEN.")
    pp["status"] = "CERTIFIED"
    pp["certified_by_user_id"] = uid
    touch(pp)
    return jsonify(envelope_object(ser_purchase_period(pp))), 200


@app.post("/purchase-periods/<rid>/cancel")
def cancel_purchase_period(rid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    pp = get_or_404(store.purchase_periods, rid)
    if pp["status"] not in ("PENDING", "OPEN", "CERTIFIED"):
        raise err(409, "ERR_INVALID_STATE", "Batch cannot be cancelled from its current state.")
    pp["status"] = "CANCELLED"
    touch(pp)
    return jsonify(envelope_object(ser_purchase_period(pp))), 200


@app.post("/purchase-periods/<rid>/run-purchase")
def run_purchase(rid):
    uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    pp = get_or_404(store.purchase_periods, rid)
    body = get_body()

    if "expected_purchase_period_version" not in body:
        raise err(400, "ERR_VALIDATION", "expected_purchase_period_version is required.")
    expected = body.get("expected_purchase_period_version")
    if not is_int(expected):
        raise err(400, "ERR_VALIDATION", "expected_purchase_period_version must be an integer.")

    if pp["status"] != "CERTIFIED":
        raise err(409, "ERR_NOT_CERTIFIED", "run-purchase requires PurchasePeriod CERTIFIED.")

    if expected != pp["version"]:
        raise err(412, "ERR_STALE_VERSION", "expected_purchase_period_version does not match.")

    if pp["certified_by_user_id"] is not None and uid == pp["certified_by_user_id"]:
        raise err(409, "ERR_SEGREGATION_OF_DUTIES",
                  "run-purchase actor must differ from the certifying officer.")

    o = store.offering_periods[pp["offering_period_id"]]
    plan = store.plans[o["plan_id"]]

    if plan["lookback_enabled"]:
        applicable_fmv = min(o["grant_date_fmv_cents"], pp["purchase_date_fmv_cents"])
    else:
        applicable_fmv = pp["purchase_date_fmv_cents"]
    numerator_x100 = applicable_fmv * (100 - plan["discount_pct"])
    price_per_share = round_half_up_over_100(numerator_x100)

    tax_year = pp["_purchase_d"].year
    annual_cap_cents = plan["annual_purchase_limit_usd"] * 100

    enrolls = [e for e in store.enrollments.values()
               if e["offering_period_id"] == o["id"] and e["status"] == "ENROLLED"]
    enrolls = sort_by_created(enrolls)

    for e in enrolls:
        participant_id = e["participant_id"]
        ledger = _get_or_create_ledger(participant_id, tax_year, annual_cap_cents)

        remaining_grant_capacity = max(0, annual_cap_cents - ledger["accrued_grant_value_cents"])
        if o["grant_date_fmv_cents"] > 0:
            max_shares_by_cap = remaining_grant_capacity // o["grant_date_fmv_cents"]
        else:
            max_shares_by_cap = 0
        if price_per_share > 0:
            max_shares_by_cash = e["accumulated_contribution_cents"] // price_per_share
        else:
            max_shares_by_cash = 0
        shares = min(max_shares_by_cap, max_shares_by_cash)

        spend = shares * price_per_share
        grant_value_applied = shares * o["grant_date_fmv_cents"]
        residual = e["accumulated_contribution_cents"] - spend

        purchase = {
            "id": new_id(), "enrollment_id": e["id"], "purchase_period_id": pp["id"],
            "price_per_share_cents": price_per_share, "shares_purchased": shares,
            "spend_cents": spend, "residual_cents": residual,
            "grant_date_value_applied_cents": grant_value_applied, "status": "SETTLED",
        }
        common_init(purchase)
        store.purchases[purchase["id"]] = purchase

        lot = {
            "id": new_id(), "purchase_id": purchase["id"], "participant_id": participant_id,
            "shares_total": shares, "shares_remaining": shares,
            "grant_date": o["grant_date"], "purchase_date": pp["purchase_date"],
            "status": "OPEN", "_grant_d": o["_grant_d"], "_purchase_d": pp["_purchase_d"],
        }
        common_init(lot)
        store.share_lots[lot["id"]] = lot

        for c in store.contributions.values():
            if c["enrollment_id"] == e["id"] and c["status"] == "POSTED":
                c["status"] = "CONSUMED"

        e["accumulated_contribution_cents"] = 0
        e["refunded_contribution_cents"] += residual
        touch(e)

        ledger["accrued_grant_value_cents"] += grant_value_applied
        ledger["remaining_capacity_cents"] = max(0, annual_cap_cents - ledger["accrued_grant_value_cents"])
        touch(ledger)

        form = {
            "id": new_id(), "purchase_id": purchase["id"], "participant_id": participant_id,
            "box3_grant_date_fmv_cents": o["grant_date_fmv_cents"],
            "box4_purchase_date_fmv_cents": pp["purchase_date_fmv_cents"],
            "box5_price_paid_cents": price_per_share, "box6_shares": shares,
            "tax_year": tax_year, "issued_by_user_id": pp["certified_by_user_id"],
        }
        common_init(form)
        store.forms[form["id"]] = form

    pp["status"] = "PURCHASED"
    touch(pp)

    siblings = [s for s in store.purchase_periods.values()
                if s["offering_period_id"] == o["id"]]
    all_terminal = all(s["status"] in ("PURCHASED", "CANCELLED") for s in siblings)
    any_purchased = any(s["status"] == "PURCHASED" for s in siblings)
    if o["status"] == "ACTIVE" and all_terminal and any_purchased:
        o["status"] = "CLOSED"
        touch(o)
        for e in store.enrollments.values():
            if e["offering_period_id"] == o["id"] and e["status"] == "ENROLLED":
                e["status"] = "COMPLETED"
                touch(e)

    return jsonify(envelope_object(ser_purchase_period(pp))), 200


def _get_or_create_ledger(participant_id, year, annual_cap_cents):
    for l in store.accrual_ledgers.values():
        if l["participant_id"] == participant_id and l["calendar_year"] == year:
            return l
    rec = {
        "id": new_id(), "participant_id": participant_id, "calendar_year": year,
        "accrued_grant_value_cents": 0, "remaining_capacity_cents": annual_cap_cents,
    }
    common_init(rec)
    store.accrual_ledgers[rec["id"]] = rec
    return rec


# ============================ Enrollments ============================

@app.post("/enrollments")
def create_enrollment():
    uid, role = authenticate()
    require_role(role, {ROLE_PARTICIPANT})
    body = get_body()

    participant_id = require_str(body, "participant_id")
    offering_period_id = require_str(body, "offering_period_id")
    rate = require_number(body, "contribution_rate_pct")

    if uid != participant_id:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only enroll themselves.")

    participant = get_or_404(store.participants, participant_id)
    offering = get_or_404(store.offering_periods, offering_period_id)
    plan = store.plans[offering["plan_id"]]

    if participant["is_five_percent_owner"]:
        raise err(422, "ERR_FIVE_PERCENT_OWNER", "Five-percent owners are barred from enrolling.")
    if participant["status"] != "ACTIVE":
        raise err(422, "ERR_PARTICIPANT_NOT_ACTIVE", "Participant must be ACTIVE to enroll.")
    if not (0 < rate <= plan["max_contribution_rate_pct"]):
        raise err(422, "ERR_RATE_EXCEEDS_LIMIT",
                  "contribution_rate_pct must be > 0 and <= plan max.")
    for e in store.enrollments.values():
        if (e["participant_id"] == participant_id
                and e["offering_period_id"] == offering_period_id
                and e["status"] in ("ENROLLED", "SUSPENDED")):
            raise err(409, "ERR_DUPLICATE_ENROLLMENT",
                      "Participant already has a non-terminal enrollment in this offering.")

    if offering["status"] != "OPEN":
        raise err(409, "ERR_INVALID_STATE", "Offering is not open for enrollment.")

    rec = {
        "id": new_id(), "participant_id": participant_id,
        "offering_period_id": offering_period_id, "contribution_rate_pct": rate,
        "status": "ENROLLED", "accumulated_contribution_cents": 0,
        "refunded_contribution_cents": 0,
    }
    common_init(rec)
    store.enrollments[rec["id"]] = rec
    return jsonify(envelope_object(ser_enrollment(rec))), 201


@app.get("/enrollments/<rid>")
def read_enrollment(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.enrollments, rid)
    if role == ROLE_PARTICIPANT and uid != rec["participant_id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own enrollment.")
    return jsonify(envelope_object(ser_enrollment(rec))), 200


@app.get("/enrollments")
def list_enrollments():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    participant_id = request.args.get("participant_id")
    offering_period_id = request.args.get("offering_period_id")
    status = request.args.get("status")
    rows = list(store.enrollments.values())
    if participant_id is not None:
        rows = [e for e in rows if e["participant_id"] == participant_id]
    if offering_period_id is not None:
        rows = [e for e in rows if e["offering_period_id"] == offering_period_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    if role == ROLE_PARTICIPANT:
        rows = [e for e in rows if e["participant_id"] == uid]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_enrollment(e) for e in page], limit, offset, total, has_more)), 200


def _check_enrollment_owner(uid, role, e):
    if role == ROLE_PARTICIPANT and uid != e["participant_id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only act on their own enrollment.")


@app.post("/enrollments/<rid>/suspend")
def suspend_enrollment(rid):
    uid, role = authenticate()
    require_role(role, {ROLE_PARTICIPANT})
    e = get_or_404(store.enrollments, rid)
    _check_enrollment_owner(uid, role, e)
    o = store.offering_periods.get(e["offering_period_id"])
    if e["status"] != "ENROLLED" or (o is not None and o["status"] == "CLOSED"):
        raise err(409, "ERR_INVALID_STATE", "suspend requires ENROLLED and offering not CLOSED.")
    e["status"] = "SUSPENDED"
    touch(e)
    return jsonify(envelope_object(ser_enrollment(e))), 200


@app.post("/enrollments/<rid>/resume")
def resume_enrollment(rid):
    uid, role = authenticate()
    require_role(role, {ROLE_PARTICIPANT})
    e = get_or_404(store.enrollments, rid)
    _check_enrollment_owner(uid, role, e)
    o = store.offering_periods.get(e["offering_period_id"])
    if e["status"] != "SUSPENDED" or (o is None or o["status"] not in ("OPEN", "ENROLLMENT_CLOSED", "ACTIVE")):
        raise err(409, "ERR_INVALID_STATE",
                  "resume requires SUSPENDED and offering OPEN/ENROLLMENT_CLOSED/ACTIVE.")
    e["status"] = "ENROLLED"
    touch(e)
    return jsonify(envelope_object(ser_enrollment(e))), 200


@app.post("/enrollments/<rid>/withdraw")
def withdraw_enrollment(rid):
    uid, role = authenticate()
    require_role(role, {ROLE_PARTICIPANT})
    e = get_or_404(store.enrollments, rid)
    _check_enrollment_owner(uid, role, e)
    if e["status"] not in ("ENROLLED", "SUSPENDED"):
        raise err(409, "ERR_INVALID_STATE", "withdraw requires ENROLLED or SUSPENDED.")
    _withdraw_enrollment(e)
    return jsonify(envelope_object(ser_enrollment(e))), 200


def _withdraw_enrollment(e):
    refunded = 0
    for c in store.contributions.values():
        if c["enrollment_id"] == e["id"] and c["status"] == "POSTED":
            c["status"] = "REFUNDED"
            refunded += c["amount_cents"]
    e["status"] = "WITHDRAWN"
    e["refunded_contribution_cents"] += refunded
    e["accumulated_contribution_cents"] = 0
    touch(e)


# ============================ Contributions ============================

@app.post("/contributions")
def create_contribution():
    _uid, role = authenticate()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    enrollment_id = require_str(body, "enrollment_id")
    pay_date_raw, _pd = require_date(body, "pay_date")
    gross = require_int(body, "gross_pay_cents")
    if not (gross > 0):
        raise err(400, "ERR_VALIDATION", "gross_pay_cents must be > 0.")

    e = get_or_404(store.enrollments, enrollment_id)
    if e["status"] != "ENROLLED":
        raise err(409, "ERR_ENROLLMENT_NOT_CONTRIBUTING",
                  "Contributions may only be posted to an ENROLLED enrollment.")

    rate = e["contribution_rate_pct"]
    amount = int((gross * rate) // 100)

    rec = {
        "id": new_id(), "enrollment_id": enrollment_id, "pay_date": pay_date_raw,
        "gross_pay_cents": gross, "amount_cents": amount, "status": "POSTED",
        "created_at": now_iso(),
    }
    store.contributions[rec["id"]] = rec

    e["accumulated_contribution_cents"] += amount
    touch(e)
    return jsonify(envelope_object(ser_contribution(rec))), 201


@app.get("/contributions/<rid>")
def read_contribution(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.contributions, rid)
    if role == ROLE_PARTICIPANT:
        e = store.enrollments.get(rec["enrollment_id"])
        if e is None or uid != e["participant_id"]:
            raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own contributions.")
    return jsonify(envelope_object(ser_contribution(rec))), 200


@app.get("/contributions")
def list_contributions():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    rows = list(store.contributions.values())
    if enrollment_id is not None:
        rows = [c for c in rows if c["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if role == ROLE_PARTICIPANT:
        owned = {e["id"] for e in store.enrollments.values() if e["participant_id"] == uid}
        rows = [c for c in rows if c["enrollment_id"] in owned]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_contribution(c) for c in page], limit, offset, total, has_more)), 200


# ============================ Purchases ============================

@app.get("/purchases/<rid>")
def read_purchase(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.purchases, rid)
    if role == ROLE_PARTICIPANT:
        e = store.enrollments.get(rec["enrollment_id"])
        if e is None or uid != e["participant_id"]:
            raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own purchases.")
    return jsonify(envelope_object(ser_purchase(rec))), 200


@app.get("/purchases")
def list_purchases():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    enrollment_id = request.args.get("enrollment_id")
    purchase_period_id = request.args.get("purchase_period_id")
    rows = list(store.purchases.values())
    if enrollment_id is not None:
        rows = [p for p in rows if p["enrollment_id"] == enrollment_id]
    if purchase_period_id is not None:
        rows = [p for p in rows if p["purchase_period_id"] == purchase_period_id]
    if role == ROLE_PARTICIPANT:
        owned = {e["id"] for e in store.enrollments.values() if e["participant_id"] == uid}
        rows = [p for p in rows if p["enrollment_id"] in owned]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_purchase(p) for p in page], limit, offset, total, has_more)), 200


@app.post("/purchases/<rid>/form-3922")
def issue_form(rid):
    uid, role = authenticate()
    require_role(role, {ROLE_OFFICER})
    purchase = get_or_404(store.purchases, rid)

    for f in store.forms.values():
        if f["purchase_id"] == rid:
            raise err(409, "ERR_FORM_ALREADY_ISSUED", "Form 3922 already issued for this purchase.")

    pp = store.purchase_periods[purchase["purchase_period_id"]]
    o = store.offering_periods[pp["offering_period_id"]]
    e = store.enrollments[purchase["enrollment_id"]]

    form = {
        "id": new_id(), "purchase_id": rid, "participant_id": e["participant_id"],
        "box3_grant_date_fmv_cents": o["grant_date_fmv_cents"],
        "box4_purchase_date_fmv_cents": pp["purchase_date_fmv_cents"],
        "box5_price_paid_cents": purchase["price_per_share_cents"],
        "box6_shares": purchase["shares_purchased"],
        "tax_year": pp["_purchase_d"].year, "issued_by_user_id": uid,
    }
    common_init(form)
    store.forms[form["id"]] = form
    return jsonify(envelope_object(ser_form(form))), 201


@app.get("/purchases/<rid>/form-3922")
def list_forms_for_purchase(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    get_or_404(store.purchases, rid)
    limit, offset = get_pagination()
    rows = [f for f in store.forms.values() if f["purchase_id"] == rid]
    if role == ROLE_PARTICIPANT:
        rows = [f for f in rows if f["participant_id"] == uid]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_form(f) for f in page], limit, offset, total, has_more)), 200


@app.get("/form-3922/<rid>")
def read_form(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.forms, rid)
    if role == ROLE_PARTICIPANT and uid != rec["participant_id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own forms.")
    return jsonify(envelope_object(ser_form(rec))), 200


@app.get("/form-3922")
def list_forms():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    participant_id = request.args.get("participant_id")
    purchase_id = request.args.get("purchase_id")
    rows = list(store.forms.values())
    if participant_id is not None:
        rows = [f for f in rows if f["participant_id"] == participant_id]
    if purchase_id is not None:
        rows = [f for f in rows if f["purchase_id"] == purchase_id]
    if role == ROLE_PARTICIPANT:
        rows = [f for f in rows if f["participant_id"] == uid]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_form(f) for f in page], limit, offset, total, has_more)), 200


# ============================ Share lots ============================

@app.get("/share-lots/<rid>")
def read_share_lot(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.share_lots, rid)
    if role == ROLE_PARTICIPANT and uid != rec["participant_id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own share lots.")
    return jsonify(envelope_object(ser_share_lot(rec))), 200


@app.get("/share-lots")
def list_share_lots():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    participant_id = request.args.get("participant_id")
    purchase_id = request.args.get("purchase_id")
    status = request.args.get("status")
    rows = list(store.share_lots.values())
    if participant_id is not None:
        rows = [s for s in rows if s["participant_id"] == participant_id]
    if purchase_id is not None:
        rows = [s for s in rows if s["purchase_id"] == purchase_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if role == ROLE_PARTICIPANT:
        rows = [s for s in rows if s["participant_id"] == uid]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_share_lot(s) for s in page], limit, offset, total, has_more)), 200


# ============================ Dispositions ============================

@app.post("/dispositions")
def create_disposition():
    uid, role = authenticate()
    require_role(role, {ROLE_PARTICIPANT})
    body = get_body()

    share_lot_id = require_str(body, "share_lot_id")
    participant_id = require_str(body, "participant_id")
    sale_date_raw, sale_d = require_date(body, "sale_date")
    shares_sold = require_int(body, "shares_sold")
    sale_price = require_int(body, "sale_price_per_share_cents")
    if not (sale_price >= 0):
        raise err(400, "ERR_VALIDATION", "sale_price_per_share_cents must be >= 0.")

    if uid != participant_id:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only dispose their own shares.")

    lot = get_or_404(store.share_lots, share_lot_id)
    get_or_404(store.participants, participant_id)

    if lot["participant_id"] != uid:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Share lot is not owned by the acting participant.")

    if lot["status"] != "OPEN":
        raise err(409, "ERR_INVALID_STATE", "Share lot is not OPEN.")

    if sale_d < lot["_purchase_d"]:
        raise err(422, "ERR_SALE_BEFORE_PURCHASE", "sale_date must be on or after purchase_date.")

    if not (0 < shares_sold <= lot["shares_remaining"]):
        raise err(422, "ERR_INSUFFICIENT_SHARES", "shares_sold must be > 0 and <= shares_remaining.")

    purchase = store.purchases[lot["purchase_id"]]
    pp = store.purchase_periods[purchase["purchase_period_id"]]
    o = store.offering_periods[pp["offering_period_id"]]

    price_paid = purchase["price_per_share_cents"]
    grant_fmv = o["grant_date_fmv_cents"]
    purchase_fmv = pp["purchase_date_fmv_cents"]

    qualifying = (sale_d >= add_years(lot["_grant_d"], 2)
                  and sale_d >= add_years(lot["_purchase_d"], 1))
    disposition_type = "QUALIFYING" if qualifying else "DISQUALIFYING"

    sale_proceeds = shares_sold * sale_price
    purchase_cost = shares_sold * price_paid

    if disposition_type == "QUALIFYING":
        actual_gain = max(0, sale_proceeds - purchase_cost)
        statutory_discount = shares_sold * max(0, grant_fmv - price_paid)
        ordinary_income = min(actual_gain, statutory_discount)
    else:
        ordinary_income = shares_sold * max(0, purchase_fmv - price_paid)

    adjusted_basis = purchase_cost + ordinary_income
    capital_gain = sale_proceeds - adjusted_basis

    rec = {
        "id": new_id(), "share_lot_id": share_lot_id, "participant_id": participant_id,
        "sale_date": sale_date_raw, "shares_sold": shares_sold,
        "sale_price_per_share_cents": sale_price, "disposition_type": disposition_type,
        "ordinary_income_cents": ordinary_income, "capital_gain_cents": capital_gain,
    }
    common_init(rec)
    store.dispositions[rec["id"]] = rec

    lot["shares_remaining"] -= shares_sold
    if lot["shares_remaining"] == 0:
        lot["status"] = "FULLY_DISPOSED"
    touch(lot)

    return jsonify(envelope_object(ser_disposition(rec))), 201


@app.get("/dispositions/<rid>")
def read_disposition(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.dispositions, rid)
    if role == ROLE_PARTICIPANT and uid != rec["participant_id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own dispositions.")
    return jsonify(envelope_object(ser_disposition(rec))), 200


@app.get("/dispositions")
def list_dispositions():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    participant_id = request.args.get("participant_id")
    share_lot_id = request.args.get("share_lot_id")
    rows = list(store.dispositions.values())
    if participant_id is not None:
        rows = [d for d in rows if d["participant_id"] == participant_id]
    if share_lot_id is not None:
        rows = [d for d in rows if d["share_lot_id"] == share_lot_id]
    if role == ROLE_PARTICIPANT:
        rows = [d for d in rows if d["participant_id"] == uid]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_disposition(d) for d in page], limit, offset, total, has_more)), 200


# ============================ Accrual ledgers ============================

@app.get("/accrual-ledgers/<rid>")
def read_ledger(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(store.accrual_ledgers, rid)
    if role == ROLE_PARTICIPANT and uid != rec["participant_id"]:
        raise err(403, "ERR_NOT_RESOURCE_OWNER", "Participants may only read their own ledger.")
    return jsonify(envelope_object(ser_ledger(rec))), 200


@app.get("/accrual-ledgers")
def list_ledgers():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    participant_id = request.args.get("participant_id")
    calendar_year = request.args.get("calendar_year")
    rows = list(store.accrual_ledgers.values())
    if participant_id is not None:
        rows = [l for l in rows if l["participant_id"] == participant_id]
    if calendar_year is not None:
        try:
            cy = int(calendar_year)
        except ValueError:
            raise err(400, "ERR_VALIDATION", "calendar_year must be an integer.")
        rows = [l for l in rows if l["calendar_year"] == cy]
    if role == ROLE_PARTICIPANT:
        rows = [l for l in rows if l["participant_id"] == uid]
    rows = sort_by_created(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return jsonify(envelope_array([ser_ledger(l) for l in page], limit, offset, total, has_more)), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
