"""Water-Sewer Tap & Capacity Fee API — Flask reference implementation.

In-memory only. State is wiped on every process boot (per-test-server isolation).
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Applicant", "Developer", "UtilityReviewer", "FieldInspector", "UtilityAdmin"}

METER_SIZES = {"FIVE_EIGHTH", "THREE_QUARTER", "ONE", "ONE_AND_HALF", "TWO"}
SERVICE_TYPES = {"WATER", "SEWER", "BOTH"}
USE_TYPES = {"RESIDENTIAL", "COMMERCIAL", "IRRIGATION"}
ASSESSMENT_BASES = {"NEW", "REDEVELOPMENT"}
INSPECTION_TYPES = {"TAP", "METER_SET", "BACKFLOW"}
TXN_TYPES = {"DEPOSIT", "DRAWDOWN", "REFUND"}
LATECOMER_METHODS = {"FRONT_FOOTAGE", "AREA"}

MAX_CONNECTION_DISTANCE_FT = 200
APPOINTMENT_BUFFER = timedelta(minutes=60)

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.meter_size_schedules = {}
        self.fee_schedules = {}
        self.inspectors = {}
        self.meter_crews = {}
        self.connection_applications = {}
        self.availability_determinations = {}
        self.main_extension_projects = {}
        self.developer_agreements = {}
        self.escrow_transactions = {}
        self.inspections = {}
        self.backflow_assemblies = {}
        self.meter_sets = {}
        self.service_accounts = {}
        self.latecomer_reimbursements = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def error(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def rand_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(extra=None):
    m = {"api_request_id": rand_request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200, response_type="object", list_meta=None):
    body = {"meta": meta(list_meta), "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def obj_response(entity, status=200):
    return ok(public(entity), status=status, response_type="object")


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def base_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        error("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        error("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def get_body():
    body = request.get_json(force=True, silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        error("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def require_present(body, field):
    if field not in body or body[field] is None:
        error("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return body[field]


def require_enum(body, field, allowed):
    val = require_present(body, field)
    if val not in allowed:
        error("ERR_VALIDATION", 400, f"Invalid value for {field}")
    return val


def require_int(body, field, minimum=None):
    val = require_present(body, field)
    if not is_int(val):
        error("ERR_VALIDATION", 400, f"{field} must be an integer")
    if minimum is not None and val < minimum:
        error("ERR_VALIDATION", 400, f"{field} must be >= {minimum}")
    return val


def require_num(body, field, minimum=None, strict_min=None):
    val = require_present(body, field)
    if not is_num(val):
        error("ERR_VALIDATION", 400, f"{field} must be a number")
    if minimum is not None and val < minimum:
        error("ERR_VALIDATION", 400, f"{field} must be >= {minimum}")
    if strict_min is not None and val <= strict_min:
        error("ERR_VALIDATION", 400, f"{field} must be > {strict_min}")
    return val


def get_or_404(store, rid):
    ent = store.get(rid)
    if ent is None:
        error("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def paginate(items):
    """items: list already sorted. Returns (page_items, list_meta). Raises on bad params."""
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            error("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            error("ERR_VALIDATION", 400, "limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            error("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            error("ERR_VALIDATION", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, list_meta


def list_response(store, filters=None):
    items = sorted(store.values(), key=lambda e: e["_seq"])
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [e for e in items if str(e.get(key)) == str(val)]
    page, list_meta = paginate(items)
    return ok([public(e) for e in page], status=200, response_type="array", list_meta=list_meta)


# ---------------------------------------------------------------------------
# Domain lookups
# ---------------------------------------------------------------------------
def schedule_for_size(size):
    for row in db.meter_size_schedules.values():
        if row["meter_size"] == size:
            return row
    return None


def governing_fee_schedule():
    active = [f for f in db.fee_schedules.values() if f.get("is_active")]
    if not active:
        return None
    return max(active, key=lambda f: f["_seq"])


def latest_determination_for(app_id):
    dets = [d for d in db.availability_determinations.values() if d["application_id"] == app_id]
    if not dets:
        return None
    return max(dets, key=lambda d: d["_seq"])


def determinations_for(app_id):
    return [d for d in db.availability_determinations.values() if d["application_id"] == app_id]


def recompute_escrow(agreement):
    aid = agreement["id"]
    dep = sum(t["amount_cents"] for t in db.escrow_transactions.values()
              if t["developer_agreement_id"] == aid and t["txn_type"] == "DEPOSIT")
    drawn = sum(t["amount_cents"] for t in db.escrow_transactions.values()
                if t["developer_agreement_id"] == aid and t["txn_type"] == "DRAWDOWN")
    refunded = sum(t["amount_cents"] for t in db.escrow_transactions.values()
                   if t["developer_agreement_id"] == aid and t["txn_type"] == "REFUND")
    agreement["escrow_deposited_cents"] = dep
    agreement["escrow_drawn_cents"] = drawn
    agreement["escrow_refunded_cents"] = refunded
    agreement["escrow_held_cents"] = dep - drawn - refunded


def append_escrow_txn(agreement, txn_type, amount, memo=""):
    txn = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "developer_agreement_id": agreement["id"],
        "txn_type": txn_type,
        "amount_cents": amount,
        "memo": memo,
    }
    db.escrow_transactions[txn["id"]] = txn
    recompute_escrow(agreement)
    return txn


# =============================================================================
# Configuration & resources
# =============================================================================
@app.post("/meter-size-schedules")
def create_meter_size_schedule():
    authenticate({"UtilityAdmin"})
    body = get_body()
    meter_size = require_enum(body, "meter_size", METER_SIZES)
    eru_factor = require_num(body, "eru_factor", strict_min=0)
    tap_fee = require_int(body, "tap_install_fee_cents", minimum=0)
    if schedule_for_size(meter_size) is not None:
        error("ERR_VALIDATION", 400, "meter_size already exists")
    ent = base_fields()
    ent.update({
        "meter_size": meter_size,
        "eru_factor": eru_factor,
        "tap_install_fee_cents": tap_fee,
    })
    db.meter_size_schedules[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/meter-size-schedules")
def list_meter_size_schedules():
    authenticate({"UtilityAdmin", "UtilityReviewer", "Applicant", "Developer", "FieldInspector"})
    return list_response(db.meter_size_schedules, {"meter_size": request.args.get("meter_size")})


@app.post("/fee-schedules")
def create_fee_schedule():
    authenticate({"UtilityAdmin"})
    body = get_body()
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        error("ERR_VALIDATION", 400, "is_active must be a boolean")
    water = require_int(body, "water_capacity_fee_per_eru_cents", minimum=0)
    sewer = require_int(body, "sewer_capacity_fee_per_eru_cents", minimum=0)
    use_mult = require_present(body, "use_multipliers")
    if not isinstance(use_mult, dict):
        error("ERR_VALIDATION", 400, "use_multipliers must be an object")
    admin_pct = require_num(body, "admin_fee_pct", minimum=0)
    admin_cap = require_int(body, "admin_fee_cap_cents", minimum=0)
    vol_threshold = require_int(body, "volume_discount_threshold_cents", minimum=0)
    vol_pct = require_num(body, "volume_discount_pct", minimum=0)
    pavement = require_int(body, "pavement_cut_surcharge_cents", minimum=0)
    ent = base_fields()
    ent.update({
        "is_active": is_active,
        "water_capacity_fee_per_eru_cents": water,
        "sewer_capacity_fee_per_eru_cents": sewer,
        "use_multipliers": use_mult,
        "admin_fee_pct": admin_pct,
        "admin_fee_cap_cents": admin_cap,
        "volume_discount_threshold_cents": vol_threshold,
        "volume_discount_pct": vol_pct,
        "pavement_cut_surcharge_cents": pavement,
    })
    db.fee_schedules[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/fee-schedules")
def list_fee_schedules():
    authenticate({"UtilityAdmin", "UtilityReviewer"})
    filt = {}
    if "is_active" in request.args:
        filt_val = request.args.get("is_active")
        # compare against stored boolean string
        return list_response(db.fee_schedules, {"is_active": filt_val.lower() == "true"
                             if isinstance(filt_val, str) else filt_val})
    return list_response(db.fee_schedules, filt)


@app.post("/inspectors")
def create_inspector():
    authenticate({"UtilityAdmin"})
    body = get_body()
    name = require_present(body, "name")
    if not isinstance(name, str):
        error("ERR_VALIDATION", 400, "name must be a string")
    active = body.get("active", True)
    if not isinstance(active, bool):
        error("ERR_VALIDATION", 400, "active must be a boolean")
    ent = base_fields()
    ent.update({"name": name, "active": active})
    db.inspectors[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/inspectors")
def list_inspectors():
    authenticate({"UtilityAdmin", "FieldInspector", "UtilityReviewer"})
    filt = {}
    if "active" in request.args:
        val = request.args.get("active")
        filt = {"active": val.lower() == "true" if isinstance(val, str) else val}
    return list_response(db.inspectors, filt)


@app.post("/meter-crews")
def create_meter_crew():
    authenticate({"UtilityAdmin"})
    body = get_body()
    name = require_present(body, "name")
    if not isinstance(name, str):
        error("ERR_VALIDATION", 400, "name must be a string")
    active = body.get("active", True)
    if not isinstance(active, bool):
        error("ERR_VALIDATION", 400, "active must be a boolean")
    ent = base_fields()
    ent.update({"name": name, "active": active})
    db.meter_crews[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/meter-crews")
def list_meter_crews():
    authenticate({"UtilityAdmin", "FieldInspector"})
    filt = {}
    if "active" in request.args:
        val = request.args.get("active")
        filt = {"active": val.lower() == "true" if isinstance(val, str) else val}
    return list_response(db.meter_crews, filt)


# =============================================================================
# Connection application lifecycle
# =============================================================================
@app.post("/connection-applications")
def create_connection_application():
    uid, role = authenticate({"Applicant"})
    body = get_body()
    parcel_id = require_present(body, "parcel_id")
    if not isinstance(parcel_id, str):
        error("ERR_VALIDATION", 400, "parcel_id must be a string")
    service_type = require_enum(body, "service_type", SERVICE_TYPES)
    meter_size = require_enum(body, "meter_size", METER_SIZES)
    use_type = require_enum(body, "use_type", USE_TYPES)
    requires_pavement_cut = body.get("requires_pavement_cut", False)
    if not isinstance(requires_pavement_cut, bool):
        error("ERR_VALIDATION", 400, "requires_pavement_cut must be a boolean")
    prior_credit_eru = body.get("prior_credit_eru", 0)
    if not is_num(prior_credit_eru) or prior_credit_eru < 0:
        error("ERR_VALIDATION", 400, "prior_credit_eru must be a number >= 0")
    assessment_basis = body.get("assessment_basis", "NEW")
    if assessment_basis not in ASSESSMENT_BASES:
        error("ERR_VALIDATION", 400, "invalid assessment_basis")
    ent = base_fields()
    ent.update({
        "applicant_user_id": uid,
        "parcel_id": parcel_id,
        "service_type": service_type,
        "meter_size": meter_size,
        "use_type": use_type,
        "requires_pavement_cut": requires_pavement_cut,
        "prior_credit_eru": prior_credit_eru,
        "assessment_basis": assessment_basis,
        "availability_reviewer_id": None,
        "backflow_required": None,
        "capacity_fee_cents": None,
        "tap_fee_cents": None,
        "total_fees_due_cents": None,
        "fees_paid_cents": 0,
        "status": "DRAFT",
    })
    db.connection_applications[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/connection-applications")
def list_connection_applications():
    authenticate({"Applicant", "UtilityReviewer", "UtilityAdmin"})
    filt = {
        "applicant_user_id": request.args.get("applicant_user_id"),
        "parcel_id": request.args.get("parcel_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.connection_applications, filt)


@app.get("/connection-applications/<rid>")
def get_connection_application(rid):
    authenticate({"Applicant", "UtilityReviewer", "UtilityAdmin"})
    ent = get_or_404(db.connection_applications, rid)
    return obj_response(ent)


def _app_owner_check(app_ent, uid):
    if app_ent["applicant_user_id"] != uid:
        error("ERR_UNAUTHORIZED", 403, "Applicant does not own this application")


@app.post("/connection-applications/<rid>/submit")
def submit_application(rid):
    uid, role = authenticate({"Applicant"})
    app_ent = get_or_404(db.connection_applications, rid)
    _app_owner_check(app_ent, uid)
    # meter_size known (priority 5, before state)
    if schedule_for_size(app_ent["meter_size"]) is None:
        error("ERR_METER_SIZE_UNKNOWN", 422, "meter_size does not match a schedule row")
    if app_ent["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        error("ERR_INVALID_STATE", 409, "Cannot submit from current state")
    # required fields present
    for f in ("parcel_id", "service_type", "meter_size", "use_type"):
        if app_ent.get(f) is None:
            error("ERR_VALIDATION", 400, f"Missing {f}")
    app_ent["status"] = "SUBMITTED"
    touch(app_ent)
    return obj_response(app_ent)


@app.post("/connection-applications/<rid>/start-review")
def start_review(rid):
    authenticate({"UtilityReviewer"})
    app_ent = get_or_404(db.connection_applications, rid)
    if app_ent["status"] != "SUBMITTED":
        error("ERR_INVALID_STATE", 409, "Application is not SUBMITTED")
    app_ent["status"] = "UNDER_REVIEW"
    touch(app_ent)
    return obj_response(app_ent)


@app.post("/connection-applications/<rid>/request-revision")
def request_revision(rid):
    authenticate({"UtilityReviewer"})
    app_ent = get_or_404(db.connection_applications, rid)
    if app_ent["status"] != "UNDER_REVIEW":
        error("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    app_ent["status"] = "REVISION_REQUESTED"
    touch(app_ent)
    return obj_response(app_ent)


@app.post("/connection-applications/<rid>/deny")
def deny_application(rid):
    authenticate({"UtilityReviewer"})
    app_ent = get_or_404(db.connection_applications, rid)
    if app_ent["status"] != "UNDER_REVIEW":
        error("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    app_ent["status"] = "DENIED"
    touch(app_ent)
    return obj_response(app_ent)


def compute_capacity_fee(app_ent, fee, schedule):
    base = Decimal(str(schedule["eru_factor"]))
    if app_ent["assessment_basis"] == "REDEVELOPMENT":
        net = base - Decimal(str(app_ent["prior_credit_eru"]))
        if net < 0:
            net = Decimal(0)
    else:
        net = base
    service = app_ent["service_type"]
    water_comp = Decimal(fee["water_capacity_fee_per_eru_cents"]) * net if service in ("WATER", "BOTH") else Decimal(0)
    sewer_comp = Decimal(fee["sewer_capacity_fee_per_eru_cents"]) * net if service in ("SEWER", "BOTH") else Decimal(0)
    mult_val = fee["use_multipliers"].get(app_ent["use_type"], 1)
    mult = Decimal(str(mult_val))
    return round_half_up((water_comp + sewer_comp) * mult)


def compute_tap_fee(app_ent, fee, schedule):
    tap = schedule["tap_install_fee_cents"]
    if app_ent["requires_pavement_cut"]:
        tap += fee["pavement_cut_surcharge_cents"]
    return tap


def compute_total_fees(capacity, tap, fee):
    subtotal = capacity + tap
    admin = round_half_up(Decimal(subtotal) * Decimal(str(fee["admin_fee_pct"])))
    admin = min(admin, fee["admin_fee_cap_cents"])
    gross = subtotal + admin
    if gross >= fee["volume_discount_threshold_cents"]:
        discount = round_half_up(Decimal(gross) * Decimal(str(fee["volume_discount_pct"])))
    else:
        discount = 0
    return gross - discount


@app.post("/connection-applications/<rid>/approve")
def approve_application(rid):
    uid, role = authenticate({"UtilityReviewer"})
    app_ent = get_or_404(db.connection_applications, rid)
    # meter size known (priority 5)
    schedule = schedule_for_size(app_ent["meter_size"])
    if schedule is None:
        error("ERR_METER_SIZE_UNKNOWN", 422, "meter_size does not match a schedule row")
    # state (priority 6)
    if app_ent["status"] != "UNDER_REVIEW":
        error("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    # segregation of duties (priority 7)
    if app_ent["availability_reviewer_id"] is not None and uid == app_ent["availability_reviewer_id"]:
        error("ERR_SEGREGATION_OF_DUTIES", 403, "Approver cannot be the availability reviewer")
    # availability determination exists (priority 8)
    det = latest_determination_for(app_ent["id"])
    if det is None:
        error("ERR_DETERMINATION_MISSING", 422, "No availability determination for this application")
    # service available (priority 9)
    service = app_ent["service_type"]
    needs_water = service in ("WATER", "BOTH")
    needs_sewer = service in ("SEWER", "BOTH")
    available = True
    if needs_water and not det["water_main_available"]:
        available = False
    if needs_sewer and not det["sewer_main_available"]:
        available = False
    if not available:
        covered = False
        proj_ids = [p["id"] for p in db.main_extension_projects.values()
                    if p["application_id"] == app_ent["id"]]
        for ag in db.developer_agreements.values():
            if ag["main_extension_project_id"] in proj_ids and \
               ag["status"] in ("EXECUTED", "COMPLETION_PENDING", "CLOSED"):
                covered = True
                break
        if not covered:
            error("ERR_SERVICE_UNAVAILABLE", 422, "Service is not available for a requested utility")
    # assess fees
    fee = governing_fee_schedule()
    if fee is None:
        error("ERR_VALIDATION", 400, "No governing fee schedule configured")
    capacity = compute_capacity_fee(app_ent, fee, schedule)
    tap = compute_tap_fee(app_ent, fee, schedule)
    total = compute_total_fees(capacity, tap, fee)
    app_ent["capacity_fee_cents"] = capacity
    app_ent["tap_fee_cents"] = tap
    app_ent["total_fees_due_cents"] = total
    backflow_required = app_ent["use_type"] in ("COMMERCIAL", "IRRIGATION")
    app_ent["backflow_required"] = backflow_required
    app_ent["status"] = "APPROVED"
    touch(app_ent)
    if backflow_required:
        assembly = base_fields()
        assembly.update({
            "application_id": app_ent["id"],
            "serial_number": "",
            "status": "REQUIRED",
        })
        db.backflow_assemblies[assembly["id"]] = assembly
    return obj_response(app_ent)


@app.post("/connection-applications/<rid>/pay-fees")
def pay_fees(rid):
    uid, role = authenticate({"Applicant"})
    app_ent = get_or_404(db.connection_applications, rid)
    _app_owner_check(app_ent, uid)
    body = get_body()
    amount = require_int(body, "amount_cents", minimum=0)
    app_ent["fees_paid_cents"] += amount
    touch(app_ent)
    return obj_response(app_ent)


@app.post("/connection-applications/<rid>/activate")
def activate_application(rid):
    uid, role = authenticate({"Applicant"})
    app_ent = get_or_404(db.connection_applications, rid)
    _app_owner_check(app_ent, uid)
    if app_ent["status"] != "READY_FOR_ACTIVATION":
        error("ERR_INVALID_STATE", 409, "Application is not READY_FOR_ACTIVATION")
    if app_ent["backflow_required"]:
        assembly = next((a for a in db.backflow_assemblies.values()
                         if a["application_id"] == app_ent["id"]), None)
        if assembly is None or assembly["status"] != "CERTIFIED":
            error("ERR_BACKFLOW_NOT_CERTIFIED", 422, "Backflow assembly is not CERTIFIED")
    if app_ent["fees_paid_cents"] < (app_ent["total_fees_due_cents"] or 0):
        error("ERR_FEES_UNPAID", 402, "Fees not fully paid")
    app_ent["status"] = "ACTIVATED"
    touch(app_ent)
    account = base_fields()
    account.update({
        "application_id": app_ent["id"],
        "account_number": "ACCT-" + uuid.uuid4().hex[:10].upper(),
        "status": "ACTIVE",
    })
    db.service_accounts[account["id"]] = account
    return obj_response(app_ent)


@app.post("/connection-applications/<rid>/withdraw")
def withdraw_application(rid):
    uid, role = authenticate({"Applicant"})
    app_ent = get_or_404(db.connection_applications, rid)
    _app_owner_check(app_ent, uid)
    if app_ent["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED"):
        error("ERR_INVALID_STATE", 409, "Cannot withdraw from current state")
    app_ent["status"] = "WITHDRAWN"
    touch(app_ent)
    return obj_response(app_ent)


# =============================================================================
# Availability determinations
# =============================================================================
@app.post("/availability-determinations")
def create_availability_determination():
    uid, role = authenticate({"UtilityReviewer"})
    body = get_body()
    application_id = require_present(body, "application_id")
    app_ent = db.connection_applications.get(application_id)
    if app_ent is None:
        error("ERR_NOT_FOUND", 404, "application_id not found")
    distance = require_num(body, "distance_to_main_ft", minimum=0)
    service = app_ent["service_type"]
    needs_water = service in ("WATER", "BOTH")
    needs_sewer = service in ("SEWER", "BOTH")
    water_avail = needs_water and (distance <= MAX_CONNECTION_DISTANCE_FT)
    sewer_avail = needs_sewer and (distance <= MAX_CONNECTION_DISTANCE_FT)
    extension_required = (needs_water and not water_avail) or (needs_sewer and not sewer_avail)
    ent = base_fields()
    ent.update({
        "application_id": application_id,
        "distance_to_main_ft": distance,
        "water_main_available": water_avail,
        "sewer_main_available": sewer_avail,
        "extension_required": extension_required,
    })
    db.availability_determinations[ent["id"]] = ent
    # stamp availability reviewer on the application (no version bump — annotation)
    app_ent["availability_reviewer_id"] = uid
    return obj_response(ent, status=201)


@app.get("/availability-determinations")
def list_availability_determinations():
    authenticate({"UtilityReviewer", "UtilityAdmin", "Applicant"})
    return list_response(db.availability_determinations,
                         {"application_id": request.args.get("application_id")})


@app.get("/availability-determinations/<rid>")
def get_availability_determination(rid):
    authenticate({"UtilityReviewer", "UtilityAdmin", "Applicant"})
    ent = get_or_404(db.availability_determinations, rid)
    return obj_response(ent)


# =============================================================================
# Main extension projects
# =============================================================================
@app.post("/main-extension-projects")
def create_main_extension_project():
    authenticate({"Developer", "UtilityReviewer"})
    body = get_body()
    application_id = require_present(body, "application_id")
    if db.connection_applications.get(application_id) is None:
        error("ERR_NOT_FOUND", 404, "application_id not found")
    developer_user_id = require_present(body, "developer_user_id")
    if not isinstance(developer_user_id, str):
        error("ERR_VALIDATION", 400, "developer_user_id must be a string")
    length_ft = require_num(body, "length_ft", strict_min=0)
    estimated_cost = require_int(body, "estimated_cost_cents", minimum=0)
    front_ft = require_num(body, "total_assessable_front_ft", strict_min=0)
    area_sqft = require_num(body, "total_assessable_area_sqft", strict_min=0)
    reimb_cap = require_int(body, "reimbursement_cap_cents", minimum=0)
    ent = base_fields()
    ent.update({
        "application_id": application_id,
        "developer_user_id": developer_user_id,
        "length_ft": length_ft,
        "estimated_cost_cents": estimated_cost,
        "total_assessable_front_ft": front_ft,
        "total_assessable_area_sqft": area_sqft,
        "actual_construction_cost_cents": None,
        "reimbursable_principal_cents": None,
        "reimbursed_collected_cents": None,
        "outstanding_recoverable_cents": None,
        "reimbursement_cap_cents": reimb_cap,
        "status": "PROPOSED",
    })
    db.main_extension_projects[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/main-extension-projects")
def list_main_extension_projects():
    authenticate({"Developer", "UtilityReviewer", "UtilityAdmin"})
    filt = {
        "application_id": request.args.get("application_id"),
        "developer_user_id": request.args.get("developer_user_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.main_extension_projects, filt)


@app.get("/main-extension-projects/<rid>")
def get_main_extension_project(rid):
    authenticate({"Developer", "UtilityReviewer", "UtilityAdmin"})
    ent = get_or_404(db.main_extension_projects, rid)
    return obj_response(ent)


@app.post("/main-extension-projects/<rid>/start-construction")
def start_construction(rid):
    uid, role = authenticate({"Developer"})
    proj = get_or_404(db.main_extension_projects, rid)
    if proj["developer_user_id"] != uid:
        error("ERR_UNAUTHORIZED", 403, "Developer does not own this project")
    if proj["status"] != "APPROVED_TO_CONSTRUCT":
        error("ERR_INVALID_STATE", 409, "Project is not APPROVED_TO_CONSTRUCT")
    proj["status"] = "UNDER_CONSTRUCTION"
    touch(proj)
    return obj_response(proj)


@app.post("/main-extension-projects/<rid>/record-inspection")
def record_project_inspection(rid):
    authenticate({"FieldInspector"})
    proj = get_or_404(db.main_extension_projects, rid)
    if proj["status"] != "UNDER_CONSTRUCTION":
        error("ERR_INVALID_STATE", 409, "Project is not UNDER_CONSTRUCTION")
    proj["status"] = "INSPECTED"
    touch(proj)
    return obj_response(proj)


@app.post("/main-extension-projects/<rid>/accept")
def accept_project(rid):
    authenticate({"UtilityReviewer"})
    proj = get_or_404(db.main_extension_projects, rid)
    if proj["status"] != "INSPECTED":
        error("ERR_INVALID_STATE", 409, "Project is not INSPECTED")
    body = get_body()
    actual = require_int(body, "actual_construction_cost_cents", minimum=0)
    proj["actual_construction_cost_cents"] = actual
    principal = min(actual, proj["reimbursement_cap_cents"])
    proj["reimbursable_principal_cents"] = principal
    proj["reimbursed_collected_cents"] = 0
    proj["outstanding_recoverable_cents"] = principal
    proj["status"] = "ACCEPTED"
    touch(proj)
    # cascade: EXECUTED developer agreement -> COMPLETION_PENDING
    ag = next((a for a in db.developer_agreements.values()
               if a["main_extension_project_id"] == proj["id"] and a["status"] == "EXECUTED"), None)
    if ag is not None:
        ag["status"] = "COMPLETION_PENDING"
        touch(ag)
        # cascade: flip the project application's availability determination
        for det in determinations_for(proj["application_id"]):
            det["water_main_available"] = True
            det["sewer_main_available"] = True
            det["extension_required"] = False
            touch(det)
    return obj_response(proj)


@app.post("/main-extension-projects/<rid>/cancel")
def cancel_project(rid):
    authenticate({"UtilityReviewer"})
    proj = get_or_404(db.main_extension_projects, rid)
    if proj["status"] not in ("PROPOSED", "APPROVED_TO_CONSTRUCT"):
        error("ERR_INVALID_STATE", 409, "Project cannot be cancelled from current state")
    proj["status"] = "CANCELLED"
    touch(proj)
    return obj_response(proj)


# =============================================================================
# Developer agreements & escrow
# =============================================================================
@app.post("/developer-agreements")
def create_developer_agreement():
    authenticate({"UtilityAdmin"})
    body = get_body()
    project_id = require_present(body, "main_extension_project_id")
    if db.main_extension_projects.get(project_id) is None:
        error("ERR_NOT_FOUND", 404, "main_extension_project_id not found")
    developer_user_id = require_present(body, "developer_user_id")
    if not isinstance(developer_user_id, str):
        error("ERR_VALIDATION", 400, "developer_user_id must be a string")
    ent = base_fields()
    ent.update({
        "main_extension_project_id": project_id,
        "developer_user_id": developer_user_id,
        "required_escrow_cents": None,
        "escrow_deposited_cents": 0,
        "escrow_drawn_cents": 0,
        "escrow_refunded_cents": 0,
        "escrow_held_cents": 0,
        "status": "DRAFT",
    })
    db.developer_agreements[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/developer-agreements")
def list_developer_agreements():
    authenticate({"UtilityAdmin", "Developer"})
    filt = {
        "main_extension_project_id": request.args.get("main_extension_project_id"),
        "developer_user_id": request.args.get("developer_user_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.developer_agreements, filt)


@app.get("/developer-agreements/<rid>")
def get_developer_agreement(rid):
    authenticate({"UtilityAdmin", "Developer"})
    ent = get_or_404(db.developer_agreements, rid)
    return obj_response(ent)


@app.post("/developer-agreements/<rid>/offer")
def offer_agreement(rid):
    authenticate({"UtilityAdmin"})
    ag = get_or_404(db.developer_agreements, rid)
    if ag["status"] != "DRAFT":
        error("ERR_INVALID_STATE", 409, "Agreement is not DRAFT")
    proj = db.main_extension_projects.get(ag["main_extension_project_id"])
    if proj is None or proj["status"] != "PROPOSED":
        error("ERR_INVALID_STATE", 409, "Referenced project is not PROPOSED")
    ag["required_escrow_cents"] = proj["estimated_cost_cents"]
    ag["status"] = "PENDING_ESCROW"
    touch(ag)
    return obj_response(ag)


@app.post("/developer-agreements/<rid>/execute")
def execute_agreement(rid):
    uid, role = authenticate({"Developer"})
    ag = get_or_404(db.developer_agreements, rid)
    if ag["developer_user_id"] != uid:
        error("ERR_UNAUTHORIZED", 403, "Developer does not own this agreement")
    if ag["status"] != "PENDING_ESCROW":
        error("ERR_INVALID_STATE", 409, "Agreement is not PENDING_ESCROW")
    if ag["escrow_held_cents"] < (ag["required_escrow_cents"] or 0):
        error("ERR_ESCROW_INSUFFICIENT", 422, "Escrow not fully funded")
    ag["status"] = "EXECUTED"
    touch(ag)
    proj = db.main_extension_projects.get(ag["main_extension_project_id"])
    if proj is not None and proj["status"] == "PROPOSED":
        proj["status"] = "APPROVED_TO_CONSTRUCT"
        touch(proj)
    return obj_response(ag)


@app.post("/developer-agreements/<rid>/escrow-transactions")
def create_escrow_transaction(rid):
    uid, role = authenticate({"Developer"})
    ag = get_or_404(db.developer_agreements, rid)
    if ag["developer_user_id"] != uid:
        error("ERR_UNAUTHORIZED", 403, "Developer does not own this agreement")
    body = get_body()
    txn_type = body.get("txn_type")
    amount = body.get("amount_cents")
    expected = body.get("expected_developer_agreement_version")
    memo = body.get("memo", "")
    # state (priority 6)
    if ag["status"] not in ("PENDING_ESCROW", "EXECUTED"):
        error("ERR_INVALID_STATE", 409, "Agreement does not accept postings in current state")
    # escrow insufficient for drawdown (priority 15)
    if txn_type == "DRAWDOWN" and is_int(amount) and amount > ag["escrow_held_cents"]:
        error("ERR_ESCROW_INSUFFICIENT", 422, "Drawdown exceeds held escrow")
    # OCC (priority 20)
    if expected is not None and expected != ag["version"]:
        error("ERR_STALE_VERSION", 412, "Agreement version is stale")
    # body validation (priority 21)
    if txn_type not in TXN_TYPES:
        error("ERR_VALIDATION", 400, "invalid txn_type")
    if not is_int(amount) or amount <= 0:
        error("ERR_VALIDATION", 400, "amount_cents must be a positive integer")
    if expected is None:
        error("ERR_VALIDATION", 400, "expected_developer_agreement_version is required")
    if memo is not None and not isinstance(memo, str):
        error("ERR_VALIDATION", 400, "memo must be a string")
    txn = append_escrow_txn(ag, txn_type, amount, memo or "")
    touch(ag)
    return obj_response(txn, status=201)


@app.get("/developer-agreements/<rid>/escrow-transactions")
def list_escrow_transactions(rid):
    authenticate({"UtilityAdmin", "Developer"})
    ag = get_or_404(db.developer_agreements, rid)
    items = sorted([t for t in db.escrow_transactions.values()
                    if t["developer_agreement_id"] == ag["id"]], key=lambda e: e["_seq"])
    txn_type = request.args.get("txn_type")
    if txn_type is not None:
        items = [t for t in items if t["txn_type"] == txn_type]
    page, list_meta = paginate(items)
    return ok([public(e) for e in page], status=200, response_type="array", list_meta=list_meta)


@app.post("/developer-agreements/<rid>/close")
def close_agreement(rid):
    authenticate({"UtilityAdmin"})
    ag = get_or_404(db.developer_agreements, rid)
    if ag["status"] != "COMPLETION_PENDING":
        error("ERR_INVALID_STATE", 409, "Agreement is not COMPLETION_PENDING")
    held = ag["escrow_held_cents"]
    if held > 0:
        append_escrow_txn(ag, "REFUND", held, "close refund")
    ag["status"] = "CLOSED"
    touch(ag)
    return obj_response(ag)


@app.post("/developer-agreements/<rid>/terminate")
def terminate_agreement(rid):
    authenticate({"UtilityAdmin"})
    ag = get_or_404(db.developer_agreements, rid)
    if ag["status"] not in ("DRAFT", "PENDING_ESCROW"):
        error("ERR_INVALID_STATE", 409, "Agreement cannot be terminated from current state")
    held = ag["escrow_held_cents"]
    if held > 0:
        append_escrow_txn(ag, "REFUND", held, "termination refund")
    ag["status"] = "TERMINATED"
    touch(ag)
    return obj_response(ag)


# =============================================================================
# Inspections
# =============================================================================
@app.post("/inspections")
def create_inspection():
    authenticate({"Applicant", "FieldInspector", "UtilityReviewer"})
    body = get_body()
    application_id = require_present(body, "application_id")
    if db.connection_applications.get(application_id) is None:
        error("ERR_NOT_FOUND", 404, "application_id not found")
    inspector_id = require_present(body, "inspector_id")
    if db.inspectors.get(inspector_id) is None:
        error("ERR_NOT_FOUND", 404, "inspector_id not found")
    inspection_type = require_enum(body, "inspection_type", INSPECTION_TYPES)
    scheduled_start = require_present(body, "scheduled_start")
    scheduled_end = require_present(body, "scheduled_end")
    try:
        parse_dt(scheduled_start)
        parse_dt(scheduled_end)
    except (ValueError, TypeError):
        error("ERR_VALIDATION", 400, "invalid datetime")
    ent = base_fields()
    ent.update({
        "application_id": application_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "REQUESTED",
    })
    db.inspections[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/inspections")
def list_inspections():
    authenticate({"Applicant", "FieldInspector", "UtilityReviewer", "UtilityAdmin"})
    filt = {
        "application_id": request.args.get("application_id"),
        "inspector_id": request.args.get("inspector_id"),
        "inspection_type": request.args.get("inspection_type"),
        "status": request.args.get("status"),
    }
    return list_response(db.inspections, filt)


@app.get("/inspections/<rid>")
def get_inspection(rid):
    authenticate({"Applicant", "FieldInspector", "UtilityReviewer", "UtilityAdmin"})
    ent = get_or_404(db.inspections, rid)
    return obj_response(ent)


def inspector_conflict(cand):
    ns = parse_dt(cand["scheduled_start"])
    ne = parse_dt(cand["scheduled_end"])
    for i in db.inspections.values():
        if i["id"] == cand["id"]:
            continue
        if i["inspector_id"] != cand["inspector_id"]:
            continue
        if i["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        es = parse_dt(i["scheduled_start"])
        ee = parse_dt(i["scheduled_end"])
        if ns < ee and ne > es:
            return True
    return False


@app.post("/inspections/<rid>/schedule")
def schedule_inspection(rid):
    authenticate({"FieldInspector"})
    insp = get_or_404(db.inspections, rid)
    if insp["status"] not in ("REQUESTED", "FAILED"):
        error("ERR_INVALID_STATE", 409, "Inspection cannot be scheduled from current state")
    body = get_body()
    if "scheduled_start" in body and body["scheduled_start"] is not None:
        insp["scheduled_start"] = body["scheduled_start"]
    if "scheduled_end" in body and body["scheduled_end"] is not None:
        insp["scheduled_end"] = body["scheduled_end"]
    try:
        start = parse_dt(insp["scheduled_start"])
        end = parse_dt(insp["scheduled_end"])
    except (ValueError, TypeError):
        error("ERR_VALIDATION", 400, "invalid datetime")
    if not end > start:
        error("ERR_INVALID_WINDOW", 422, "scheduled_end must be after scheduled_start")
    if inspector_conflict(insp):
        error("ERR_INSPECTOR_UNAVAILABLE", 409, "Inspector window overlaps another inspection")
    insp["status"] = "SCHEDULED"
    touch(insp)
    return obj_response(insp)


@app.post("/inspections/<rid>/start")
def start_inspection(rid):
    uid, role = authenticate({"FieldInspector"})
    insp = get_or_404(db.inspections, rid)
    if insp["inspector_id"] != uid:
        error("ERR_UNAUTHORIZED", 403, "Not the assigned inspector")
    if insp["status"] != "SCHEDULED":
        error("ERR_INVALID_STATE", 409, "Inspection is not SCHEDULED")
    insp["status"] = "IN_PROGRESS"
    touch(insp)
    return obj_response(insp)


@app.post("/inspections/<rid>/pass")
def pass_inspection(rid):
    authenticate({"FieldInspector"})
    insp = get_or_404(db.inspections, rid)
    if insp["status"] != "IN_PROGRESS":
        error("ERR_INVALID_STATE", 409, "Inspection is not IN_PROGRESS")
    insp["status"] = "PASSED"
    touch(insp)
    app_id = insp["application_id"]
    if insp["inspection_type"] == "METER_SET":
        ms = next((m for m in db.meter_sets.values()
                   if m["application_id"] == app_id and m["status"] == "SET"), None)
        if ms is not None:
            ms["status"] = "INSTALLED"
            touch(ms)
            app_ent = db.connection_applications.get(app_id)
            if app_ent is not None and app_ent["status"] == "APPROVED":
                app_ent["status"] = "READY_FOR_ACTIVATION"
                touch(app_ent)
    elif insp["inspection_type"] == "BACKFLOW":
        assembly = next((a for a in db.backflow_assemblies.values()
                         if a["application_id"] == app_id and a["status"] == "INSTALLED"), None)
        if assembly is not None:
            assembly["status"] = "CERTIFIED"
            touch(assembly)
    return obj_response(insp)


@app.post("/inspections/<rid>/fail")
def fail_inspection(rid):
    authenticate({"FieldInspector"})
    insp = get_or_404(db.inspections, rid)
    if insp["status"] != "IN_PROGRESS":
        error("ERR_INVALID_STATE", 409, "Inspection is not IN_PROGRESS")
    insp["status"] = "FAILED"
    touch(insp)
    if insp["inspection_type"] == "BACKFLOW":
        assembly = next((a for a in db.backflow_assemblies.values()
                         if a["application_id"] == insp["application_id"]
                         and a["status"] == "INSTALLED"), None)
        if assembly is not None:
            assembly["status"] = "FAILED"
            touch(assembly)
    return obj_response(insp)


@app.post("/inspections/<rid>/cancel")
def cancel_inspection(rid):
    authenticate({"FieldInspector"})
    insp = get_or_404(db.inspections, rid)
    if insp["status"] not in ("REQUESTED", "SCHEDULED"):
        error("ERR_INVALID_STATE", 409, "Inspection cannot be cancelled from current state")
    insp["status"] = "CANCELLED"
    touch(insp)
    return obj_response(insp)


# =============================================================================
# Meter sets
# =============================================================================
@app.post("/meter-sets")
def create_meter_set():
    authenticate({"Applicant", "FieldInspector"})
    body = get_body()
    application_id = require_present(body, "application_id")
    if db.connection_applications.get(application_id) is None:
        error("ERR_NOT_FOUND", 404, "application_id not found")
    crew_id = require_present(body, "crew_id")
    if db.meter_crews.get(crew_id) is None:
        error("ERR_NOT_FOUND", 404, "crew_id not found")
    appointment_start = require_present(body, "appointment_start")
    appointment_end = require_present(body, "appointment_end")
    try:
        parse_dt(appointment_start)
        parse_dt(appointment_end)
    except (ValueError, TypeError):
        error("ERR_VALIDATION", 400, "invalid datetime")
    ent = base_fields()
    ent.update({
        "application_id": application_id,
        "crew_id": crew_id,
        "appointment_start": appointment_start,
        "appointment_end": appointment_end,
        "status": "PENDING",
    })
    db.meter_sets[ent["id"]] = ent
    return obj_response(ent, status=201)


@app.get("/meter-sets")
def list_meter_sets():
    authenticate({"Applicant", "FieldInspector", "UtilityAdmin"})
    filt = {
        "application_id": request.args.get("application_id"),
        "crew_id": request.args.get("crew_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.meter_sets, filt)


@app.get("/meter-sets/<rid>")
def get_meter_set(rid):
    authenticate({"Applicant", "FieldInspector", "UtilityAdmin"})
    ent = get_or_404(db.meter_sets, rid)
    return obj_response(ent)


def crew_conflict(cand):
    ns = parse_dt(cand["appointment_start"])
    ne = parse_dt(cand["appointment_end"])
    for m in db.meter_sets.values():
        if m["id"] == cand["id"]:
            continue
        if m["crew_id"] != cand["crew_id"]:
            continue
        if m["status"] not in ("SCHEDULED", "SET"):
            continue
        es = parse_dt(m["appointment_start"])
        ee = parse_dt(m["appointment_end"])
        if ns < (ee + APPOINTMENT_BUFFER) and (ne + APPOINTMENT_BUFFER) > es:
            return True
    return False


@app.post("/meter-sets/<rid>/schedule")
def schedule_meter_set(rid):
    authenticate({"FieldInspector"})
    ms = get_or_404(db.meter_sets, rid)
    if ms["status"] != "PENDING":
        error("ERR_INVALID_STATE", 409, "Meter-set is not PENDING")
    body = get_body()
    if "appointment_start" in body and body["appointment_start"] is not None:
        ms["appointment_start"] = body["appointment_start"]
    if "appointment_end" in body and body["appointment_end"] is not None:
        ms["appointment_end"] = body["appointment_end"]
    try:
        start = parse_dt(ms["appointment_start"])
        end = parse_dt(ms["appointment_end"])
    except (ValueError, TypeError):
        error("ERR_VALIDATION", 400, "invalid datetime")
    if not end > start:
        error("ERR_INVALID_WINDOW", 422, "appointment_end must be after appointment_start")
    if crew_conflict(ms):
        error("ERR_CREW_UNAVAILABLE", 409, "Crew appointment violates buffer gap")
    ms["status"] = "SCHEDULED"
    touch(ms)
    return obj_response(ms)


@app.post("/meter-sets/<rid>/complete-install")
def complete_install(rid):
    authenticate({"FieldInspector"})
    ms = get_or_404(db.meter_sets, rid)
    if ms["status"] != "SCHEDULED":
        error("ERR_INVALID_STATE", 409, "Meter-set is not SCHEDULED")
    app_id = ms["application_id"]
    tap_passed = any(i for i in db.inspections.values()
                     if i["application_id"] == app_id and i["inspection_type"] == "TAP"
                     and i["status"] == "PASSED")
    if not tap_passed:
        error("ERR_INSPECTION_NOT_PASSED", 422, "TAP inspection has not passed")
    app_ent = db.connection_applications.get(app_id)
    if app_ent is not None and app_ent.get("backflow_required"):
        assembly = next((a for a in db.backflow_assemblies.values()
                         if a["application_id"] == app_id), None)
        if assembly is not None and assembly["status"] == "FAILED":
            error("ERR_INVALID_STATE", 409, "Backflow assembly is FAILED")
    ms["status"] = "SET"
    touch(ms)
    return obj_response(ms)


@app.post("/meter-sets/<rid>/remove")
def remove_meter_set(rid):
    authenticate({"UtilityAdmin"})
    ms = get_or_404(db.meter_sets, rid)
    if ms["status"] != "INSTALLED":
        error("ERR_INVALID_STATE", 409, "Meter-set is not INSTALLED")
    ms["status"] = "REMOVED"
    touch(ms)
    return obj_response(ms)


# =============================================================================
# Backflow assemblies
# =============================================================================
@app.get("/backflow-assemblies")
def list_backflow_assemblies():
    authenticate({"Applicant", "FieldInspector", "UtilityReviewer", "UtilityAdmin"})
    filt = {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.backflow_assemblies, filt)


@app.get("/backflow-assemblies/<rid>")
def get_backflow_assembly(rid):
    authenticate({"Applicant", "FieldInspector", "UtilityReviewer", "UtilityAdmin"})
    ent = get_or_404(db.backflow_assemblies, rid)
    return obj_response(ent)


@app.post("/backflow-assemblies/<rid>/install")
def install_backflow(rid):
    uid, role = authenticate({"Applicant"})
    assembly = get_or_404(db.backflow_assemblies, rid)
    app_ent = db.connection_applications.get(assembly["application_id"])
    if app_ent is not None and app_ent["applicant_user_id"] != uid:
        error("ERR_UNAUTHORIZED", 403, "Applicant does not own this assembly")
    if assembly["status"] not in ("REQUIRED", "FAILED"):
        error("ERR_INVALID_STATE", 409, "Assembly cannot be installed from current state")
    body = get_body()
    serial = require_present(body, "serial_number")
    if not isinstance(serial, str) or serial == "":
        error("ERR_VALIDATION", 400, "serial_number must be a non-empty string")
    assembly["serial_number"] = serial
    assembly["status"] = "INSTALLED"
    touch(assembly)
    return obj_response(assembly)


# =============================================================================
# Service accounts
# =============================================================================
@app.get("/service-accounts")
def list_service_accounts():
    authenticate({"Applicant", "UtilityAdmin"})
    filt = {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.service_accounts, filt)


@app.get("/service-accounts/<rid>")
def get_service_account(rid):
    authenticate({"Applicant", "UtilityAdmin"})
    ent = get_or_404(db.service_accounts, rid)
    return obj_response(ent)


@app.post("/service-accounts/<rid>/suspend")
def suspend_account(rid):
    authenticate({"UtilityAdmin"})
    acct = get_or_404(db.service_accounts, rid)
    if acct["status"] != "ACTIVE":
        error("ERR_INVALID_STATE", 409, "Account is not ACTIVE")
    acct["status"] = "SUSPENDED"
    touch(acct)
    return obj_response(acct)


@app.post("/service-accounts/<rid>/reinstate")
def reinstate_account(rid):
    authenticate({"UtilityAdmin"})
    acct = get_or_404(db.service_accounts, rid)
    if acct["status"] != "SUSPENDED":
        error("ERR_INVALID_STATE", 409, "Account is not SUSPENDED")
    acct["status"] = "ACTIVE"
    touch(acct)
    return obj_response(acct)


@app.post("/service-accounts/<rid>/close")
def close_account(rid):
    authenticate({"UtilityAdmin"})
    acct = get_or_404(db.service_accounts, rid)
    if acct["status"] not in ("ACTIVE", "SUSPENDED"):
        error("ERR_INVALID_STATE", 409, "Account cannot be closed from current state")
    acct["status"] = "CLOSED"
    touch(acct)
    return obj_response(acct)


# =============================================================================
# Latecomer reimbursements
# =============================================================================
@app.post("/latecomer-reimbursements")
def create_latecomer_reimbursement():
    authenticate({"UtilityAdmin"})
    body = get_body()
    project_id = require_present(body, "main_extension_project_id")
    proj = db.main_extension_projects.get(project_id)
    if proj is None:
        error("ERR_NOT_FOUND", 404, "main_extension_project_id not found")
    benefiting_application_id = require_present(body, "benefiting_application_id")
    if db.connection_applications.get(benefiting_application_id) is None:
        error("ERR_NOT_FOUND", 404, "benefiting_application_id not found")
    method = body.get("method")
    parcel_front_ft = body.get("parcel_front_ft")
    parcel_area_sqft = body.get("parcel_area_sqft")
    expected = body.get("expected_main_extension_project_version")
    # project accepted (needed before share computation)
    if proj["status"] != "ACCEPTED" or proj.get("reimbursable_principal_cents") is None:
        error("ERR_PROJECT_NOT_ACCEPTED", 422, "Project is not ACCEPTED")
    # OCC
    if expected is not None and expected != proj["version"]:
        error("ERR_STALE_VERSION", 412, "Project version is stale")
    # body validation for method + numerics
    if method not in LATECOMER_METHODS:
        error("ERR_VALIDATION", 400, "invalid method")
    if not is_num(parcel_front_ft) or parcel_front_ft < 0:
        error("ERR_VALIDATION", 400, "parcel_front_ft must be a number >= 0")
    if not is_num(parcel_area_sqft) or parcel_area_sqft < 0:
        error("ERR_VALIDATION", 400, "parcel_area_sqft must be a number >= 0")
    if expected is None:
        error("ERR_VALIDATION", 400, "expected_main_extension_project_version is required")
    principal = Decimal(proj["reimbursable_principal_cents"])
    if method == "FRONT_FOOTAGE":
        share = round_half_up(principal * Decimal(str(parcel_front_ft))
                              / Decimal(str(proj["total_assessable_front_ft"])))
    else:
        share = round_half_up(principal * Decimal(str(parcel_area_sqft))
                              / Decimal(str(proj["total_assessable_area_sqft"])))
    # reimbursement exceeded
    if share > proj["outstanding_recoverable_cents"]:
        error("ERR_REIMBURSEMENT_EXCEEDED", 422, "Assessed share exceeds outstanding recoverable")
    ent = base_fields()
    ent.update({
        "main_extension_project_id": project_id,
        "benefiting_application_id": benefiting_application_id,
        "method": method,
        "parcel_front_ft": parcel_front_ft,
        "parcel_area_sqft": parcel_area_sqft,
        "amount_cents": share,
        "status": "ASSESSED",
    })
    db.latecomer_reimbursements[ent["id"]] = ent
    # creating the assessment increments the project's version by one
    touch(proj)
    return obj_response(ent, status=201)


@app.get("/latecomer-reimbursements")
def list_latecomer_reimbursements():
    authenticate({"UtilityAdmin", "Developer"})
    filt = {
        "main_extension_project_id": request.args.get("main_extension_project_id"),
        "benefiting_application_id": request.args.get("benefiting_application_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.latecomer_reimbursements, filt)


@app.get("/latecomer-reimbursements/<rid>")
def get_latecomer_reimbursement(rid):
    authenticate({"UtilityAdmin", "Developer"})
    ent = get_or_404(db.latecomer_reimbursements, rid)
    return obj_response(ent)


@app.post("/latecomer-reimbursements/<rid>/collect")
def collect_latecomer(rid):
    authenticate({"UtilityAdmin"})
    reimb = get_or_404(db.latecomer_reimbursements, rid)
    if reimb["status"] != "ASSESSED":
        error("ERR_INVALID_STATE", 409, "Reimbursement is not ASSESSED")
    reimb["status"] = "COLLECTED"
    touch(reimb)
    proj = db.main_extension_projects.get(reimb["main_extension_project_id"])
    if proj is not None:
        proj["reimbursed_collected_cents"] = (proj.get("reimbursed_collected_cents") or 0) + reimb["amount_cents"]
        proj["outstanding_recoverable_cents"] = (proj.get("outstanding_recoverable_cents") or 0) - reimb["amount_cents"]
    return obj_response(reimb)


@app.post("/latecomer-reimbursements/<rid>/waive")
def waive_latecomer(rid):
    authenticate({"UtilityAdmin"})
    reimb = get_or_404(db.latecomer_reimbursements, rid)
    if reimb["status"] != "ASSESSED":
        error("ERR_INVALID_STATE", 409, "Reimbursement is not ASSESSED")
    reimb["status"] = "WAIVED"
    touch(reimb)
    return obj_response(reimb)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    resp = jsonify(body)
    resp.status_code = exc.http_status
    return resp


@app.errorhandler(404)
def handle_404(exc):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(exc):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    resp = jsonify(body)
    resp.status_code = 405
    return resp


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Unexpected error: " + str(exc)},
    }
    resp = jsonify(body)
    resp.status_code = 400
    return resp


@app.after_request
def add_connection_close(resp):
    resp.headers["Connection"] = "close"
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
