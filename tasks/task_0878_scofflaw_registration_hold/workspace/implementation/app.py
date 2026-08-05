"""Scofflaw & Registration-Hold Program API — Flask reference implementation.

In-memory only. State is wiped on every process start (per-test-server isolation).
Timestamps are driven by a logical clock (default 2026-05-01T00:00:00Z).
"""
import os
import math
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "EnforcementOfficer", "HearingClerk", "CollectionsAdmin", "Owner"}

LATE_PENALTY_PCT = Decimal("0.25")
SCOFFLAW_AMOUNT_THRESHOLD_CENTS = 50000
SCOFFLAW_COUNT_THRESHOLD = 5
BOOT_COUNT_THRESHOLD = 5
TOW_AMOUNT_THRESHOLD_CENTS = 100000
BOOT_FEE_CENTS = 15000
TOW_FEE_CENTS = 25000
ADMIN_FEE_CENTS = 5000
DAILY_STORAGE_RATE_CENTS = 4000
MAX_STORAGE_DAYS = 30
PAYMENT_PLAN_MAX_INSTALLMENTS = 12
PAYMENT_PLAN_MIN_DOWN_PCT = Decimal("0.10")
HARDSHIP_TIER_1_PCT = Decimal("0.50")
DISPUTE_WINDOW_DAYS = 21
COLLECTIONS_MIN_AGE_DAYS = 90

VIOLATION_TYPES = {"METER_EXPIRED", "NO_PERMIT", "STREET_CLEANING", "HANDICAP", "FIRE_HYDRANT"}
REGISTRATION_STATUSES = {"ACTIVE", "EXPIRED", "SUSPENDED"}
HARDSHIP_STATUSES = {"NONE", "PENDING", "APPROVED"}
PAYMENT_METHODS = {"CARD", "CASH", "CHECK", "ACH"}
ACTION_TYPES = {"BOOT", "TOW"}
HARDSHIP_TIERS = {"TIER_1", "TIER_2"}
DECISIONS = {"UPHELD", "DISMISSED"}

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.owners = {}
        self.vehicles = {}
        self.cases = {}
        self.violations = {}
        self.disputes = {}
        self.officers = {}
        self.yards = {}
        self.plans = {}
        self.payments = {}
        self.orders = {}
        self.waivers = {}
        self.referrals = {}
        self.seq = 0


db = DB()
STATE = {"clock": None}


def next_seq():
    db.seq += 1
    return db.seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class AppError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise AppError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if s is None:
        raise ValueError("None")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def clock():
    return STATE["clock"]


def now_ts():
    return format_ts(STATE["clock"])


def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def rand_req_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def meta(extra=None):
    m = {"api_request_id": rand_req_id(), "api_request_timestamp": now_ts()}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(AppError)
def handle_app_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_RESOURCE_NOT_FOUND", "message": "Not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    return uid, role


def require_owner(case, uid, role):
    if role == "Owner" and case["owner_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Owner may only act on their own case.")


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_body():
    raw = request.get_data()
    if not raw:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        err("ERR_VALIDATION", 400, "Malformed request body.")
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 400, "Request body must be an object.")
    return data


def req_str(data, field):
    v = data.get(field)
    if field not in data or not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, "Missing or invalid field: %s" % field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, "Invalid field: %s" % field)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if field not in data or isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 400, "Missing or invalid integer field: %s" % field)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, "Field %s below minimum." % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        err("ERR_VALIDATION", 400, "Missing or invalid enum field: %s" % field)
    return v


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        err("ERR_VALIDATION", 400, "Invalid enum field: %s" % field)
    return v


def req_bool(data, field):
    v = data.get(field)
    if field not in data or not isinstance(v, bool):
        err("ERR_VALIDATION", 400, "Missing or invalid boolean field: %s" % field)
    return v


def req_dt(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        err("ERR_VALIDATION", 400, "Missing or invalid datetime field: %s" % field)
    try:
        parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", 400, "Unparseable datetime field: %s" % field)
    return v


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_or_404(store, rid, error_id):
    ent = store.get(rid)
    if ent is None:
        err(error_id, 404, "Resource not found.")
    return ent


def violations_of(case):
    return [v for v in db.violations.values() if v["scofflaw_case_id"] == case["id"]]


def orders_of(case):
    return [o for o in db.orders.values() if o["scofflaw_case_id"] == case["id"]]


# ---------------------------------------------------------------------------
# Common-field mutation helpers
# ---------------------------------------------------------------------------
def base_common():
    ts = now_ts()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def base_light():
    return {"id": str(uuid.uuid4()), "created_at": now_ts(), "_seq": next_seq()}


def bump(ent):
    ent["updated_at"] = now_ts()
    ent["version"] = ent.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def late_penalty(v):
    if v["status"] in ("OUTSTANDING", "DISPUTED") and clock() >= parse_iso(v["due_at"]):
        return rhu(Decimal(v["fine_amount_cents"]) * LATE_PENALTY_PCT)
    return 0


def current_due(v):
    due = v["fine_amount_cents"] + late_penalty(v) - v["paid_amount_cents"] - v["credit_cents"]
    return due if due > 0 else 0


def order_release_fee(o):
    if o["status"] not in ("APPLIED", "RELEASED"):
        return 0
    if o["status"] == "RELEASED" and o.get("released_at"):
        as_of = parse_iso(o["released_at"])
    else:
        as_of = clock()
    if o["action_type"] == "BOOT":
        return BOOT_FEE_CENTS + ADMIN_FEE_CENTS
    # TOW
    stored_from = parse_iso(o["stored_from"])
    secs = (as_of - stored_from).total_seconds()
    storage_days = math.ceil(secs / 86400.0) if secs > 0 else 0
    if storage_days < 0:
        storage_days = 0
    billable = min(storage_days, MAX_STORAGE_DAYS)
    return TOW_FEE_CENTS + ADMIN_FEE_CENTS + billable * DAILY_STORAGE_RATE_CENTS


def yard_occupied(yard_id):
    return sum(1 for o in db.orders.values()
               if o["tow_yard_id"] == yard_id and o["action_type"] == "TOW"
               and o["status"] in ("DISPATCHED", "APPLIED"))


def intervals_overlap(a1, a2, b1, b2):
    # half-open [start, end); adjacency (touching) allowed
    return a1 < b2 and b1 < a2


# ---------------------------------------------------------------------------
# Case recompute (balances, posture, eligibility, cascades)
# ---------------------------------------------------------------------------
def recompute_case(case):
    collectible = 0
    assessed = 0
    oc = 0
    for v in violations_of(case):
        st = v["status"]
        if st == "OUTSTANDING":
            cd = current_due(v)
            collectible += cd
            assessed += cd
            oc += 1
        elif st == "DISPUTED":
            assessed += current_due(v)
    case["collectible_balance_cents"] = collectible
    case["assessed_balance_cents"] = assessed
    case["outstanding_count"] = oc

    old = case["case_status"]
    new = old
    if old in ("COMPLIANT", "RESOLVED"):
        if collectible >= SCOFFLAW_AMOUNT_THRESHOLD_CENTS or oc >= SCOFFLAW_COUNT_THRESHOLD:
            new = "SCOFFLAW"
    elif old == "SCOFFLAW":
        active = any(o["status"] in ("DISPATCHED", "APPLIED") for o in orders_of(case))
        if collectible == 0 and not active:
            new = "RESOLVED"
        elif 0 < collectible < SCOFFLAW_AMOUNT_THRESHOLD_CENTS and oc < SCOFFLAW_COUNT_THRESHOLD:
            new = "COMPLIANT"

    if new != old:
        case["case_status"] = new
        if old == "SCOFFLAW" and new == "COMPLIANT":
            for o in orders_of(case):
                if o["status"] == "DISPATCHED":
                    o["status"] = "CANCELLED"
                    bump(o)
        if old == "SCOFFLAW" and new == "RESOLVED":
            if case["hold_status"] == "HOLD_PLACED":
                case["hold_status"] = "HOLD_RELEASED"
                veh = db.vehicles.get(case["vehicle_id"])
                if veh is not None:
                    veh["hold_flag"] = False
                    bump(veh)

    case["eligible_for_boot"] = (case["case_status"] == "SCOFFLAW"
                                 and case["outstanding_count"] >= BOOT_COUNT_THRESHOLD)
    case["eligible_for_tow"] = (case["case_status"] == "SCOFFLAW"
                                and case["collectible_balance_cents"] >= TOW_AMOUNT_THRESHOLD_CENTS)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_owner(o):
    return {"id": o["id"], "full_name": o["full_name"], "dmv_customer_id": o["dmv_customer_id"],
            "email": o["email"], "mailing_state": o["mailing_state"],
            "hardship_status": o["hardship_status"],
            "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"]}


def ser_vehicle(v):
    return {"id": v["id"], "owner_id": v["owner_id"], "plate_number": v["plate_number"],
            "plate_state": v["plate_state"], "vin": v["vin"],
            "registration_status": v["registration_status"], "hold_flag": v["hold_flag"],
            "created_at": v["created_at"], "updated_at": v["updated_at"], "version": v["version"]}


def ser_case(c):
    return {"id": c["id"], "vehicle_id": c["vehicle_id"], "owner_id": c["owner_id"],
            "case_status": c["case_status"], "hold_status": c["hold_status"],
            "outstanding_count": c["outstanding_count"],
            "assessed_balance_cents": c["assessed_balance_cents"],
            "collectible_balance_cents": c["collectible_balance_cents"],
            "eligible_for_boot": c["eligible_for_boot"], "eligible_for_tow": c["eligible_for_tow"],
            "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"]}


def ser_violation(v):
    return {"id": v["id"], "scofflaw_case_id": v["scofflaw_case_id"],
            "citation_number": v["citation_number"], "violation_type": v["violation_type"],
            "fine_amount_cents": v["fine_amount_cents"], "issued_at": v["issued_at"],
            "due_at": v["due_at"], "late_penalty_cents": late_penalty(v),
            "paid_amount_cents": v["paid_amount_cents"], "credit_cents": v["credit_cents"],
            "status": v["status"], "created_at": v["created_at"],
            "updated_at": v["updated_at"], "version": v["version"]}


def ser_dispute(d):
    return {"id": d["id"], "violation_id": d["violation_id"], "officer_id": d["officer_id"],
            "reason": d["reason"], "scheduled_start": d["scheduled_start"],
            "scheduled_end": d["scheduled_end"], "filed_at": d["filed_at"],
            "decided_at": d["decided_at"], "status": d["status"],
            "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"]}


def ser_officer(o):
    return {"id": o["id"], "full_name": o["full_name"], "created_at": o["created_at"]}


def ser_yard(y):
    return {"id": y["id"], "name": y["name"], "capacity": y["capacity"],
            "occupied_slot_count": yard_occupied(y["id"]), "created_at": y["created_at"]}


def ser_plan(p):
    return {"id": p["id"], "scofflaw_case_id": p["scofflaw_case_id"],
            "total_amount_cents": p["total_amount_cents"],
            "installment_count": p["installment_count"],
            "down_payment_cents": p["down_payment_cents"],
            "installment_amount_cents": p["installment_amount_cents"],
            "paid_to_date_cents": p["paid_to_date_cents"], "missed_count": p["missed_count"],
            "status": p["status"], "created_at": p["created_at"],
            "updated_at": p["updated_at"], "version": p["version"]}


def ser_payment(p):
    return {"id": p["id"], "scofflaw_case_id": p["scofflaw_case_id"],
            "amount_cents": p["amount_cents"], "method": p["method"],
            "allocation": p["allocation"], "applied_at": p["applied_at"],
            "created_at": p["created_at"]}


def ser_order(o):
    return {"id": o["id"], "scofflaw_case_id": o["scofflaw_case_id"],
            "action_type": o["action_type"], "tow_yard_id": o["tow_yard_id"],
            "stored_from": o["stored_from"], "stored_until": o["stored_until"],
            "dispatched_by_user_id": o["dispatched_by_user_id"],
            "applied_by_user_id": o["applied_by_user_id"],
            "release_fee_paid": o["release_fee_paid"], "released_at": o["released_at"],
            "release_fee_cents": order_release_fee(o), "status": o["status"],
            "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"]}


def ser_waiver(w):
    return {"id": w["id"], "scofflaw_case_id": w["scofflaw_case_id"],
            "hardship_tier": w["hardship_tier"],
            "requested_amount_cents": w["requested_amount_cents"],
            "approved_amount_cents": w["approved_amount_cents"], "decided_at": w["decided_at"],
            "status": w["status"], "created_at": w["created_at"],
            "updated_at": w["updated_at"], "version": w["version"]}


def ser_referral(r):
    return {"id": r["id"], "scofflaw_case_id": r["scofflaw_case_id"],
            "agency_name": r["agency_name"], "referred_amount_cents": r["referred_amount_cents"],
            "settled_amount_cents": r["settled_amount_cents"], "referred_at": r["referred_at"],
            "status": r["status"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "version": r["version"]}


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def paginate_and_serialize(items, serializer):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "Invalid limit.")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit out of range.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "Invalid offset.")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset out of range.")
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    data = [serializer(e) for e in page]
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return ok(data, response_type="array", status=200, pagination=pag)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["PlatformAdmin"])
    data = get_body()
    v = data.get("to_iso8601")
    if not isinstance(v, str):
        err("ERR_VALIDATION", 400, "Missing to_iso8601.")
    try:
        STATE["clock"] = parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", 400, "Unparseable to_iso8601.")
    return ok({}, response_type="object", status=200)


# ===========================================================================
# Owners
# ===========================================================================
@app.route("/owners", methods=["POST"])
def create_owner():
    auth(["PlatformAdmin"])
    data = get_body()
    full_name = req_str(data, "full_name")
    dmv_customer_id = req_str(data, "dmv_customer_id")
    email = req_str(data, "email")
    mailing_state = req_str(data, "mailing_state")
    hardship_status = opt_enum(data, "hardship_status", HARDSHIP_STATUSES, "NONE")
    for o in db.owners.values():
        if o["dmv_customer_id"] == dmv_customer_id:
            err("ERR_VALIDATION", 400, "dmv_customer_id must be unique.")
    o = base_common()
    o.update({"full_name": full_name, "dmv_customer_id": dmv_customer_id, "email": email,
              "mailing_state": mailing_state, "hardship_status": hardship_status})
    db.owners[o["id"]] = o
    return ok(ser_owner(o), status=201)


@app.route("/owners/<rid>", methods=["GET"])
def get_owner(rid):
    auth(ROLES)
    o = get_or_404(db.owners, rid, "ERR_OWNER_NOT_FOUND")
    return ok(ser_owner(o))


# ===========================================================================
# Vehicles
# ===========================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    auth(["PlatformAdmin"])
    data = get_body()
    owner_id = req_str(data, "owner_id")
    plate_number = req_str(data, "plate_number")
    plate_state = req_str(data, "plate_state")
    vin = req_str(data, "vin")
    registration_status = opt_enum(data, "registration_status", REGISTRATION_STATUSES, "ACTIVE")
    get_or_404(db.owners, owner_id, "ERR_OWNER_NOT_FOUND")
    v = base_common()
    v.update({"owner_id": owner_id, "plate_number": plate_number, "plate_state": plate_state,
              "vin": vin, "registration_status": registration_status, "hold_flag": False})
    db.vehicles[v["id"]] = v
    return ok(ser_vehicle(v), status=201)


@app.route("/vehicles/<rid>", methods=["GET"])
def get_vehicle(rid):
    auth(ROLES)
    v = get_or_404(db.vehicles, rid, "ERR_VEHICLE_NOT_FOUND")
    return ok(ser_vehicle(v))


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    auth(ROLES)
    items = list(db.vehicles.values())
    owner_id = request.args.get("owner_id")
    plate_number = request.args.get("plate_number")
    if owner_id is not None:
        items = [x for x in items if x["owner_id"] == owner_id]
    if plate_number is not None:
        items = [x for x in items if x["plate_number"] == plate_number]
    return paginate_and_serialize(items, ser_vehicle)


# ===========================================================================
# Hearing officers
# ===========================================================================
@app.route("/hearing-officers", methods=["POST"])
def create_officer():
    auth(["PlatformAdmin"])
    data = get_body()
    full_name = req_str(data, "full_name")
    o = base_light()
    o.update({"full_name": full_name})
    db.officers[o["id"]] = o
    return ok(ser_officer(o), status=201)


@app.route("/hearing-officers", methods=["GET"])
def list_officers():
    auth(["PlatformAdmin", "HearingClerk"])
    return paginate_and_serialize(list(db.officers.values()), ser_officer)


# ===========================================================================
# Tow yards
# ===========================================================================
@app.route("/tow-yards", methods=["POST"])
def create_yard():
    auth(["PlatformAdmin"])
    data = get_body()
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", minimum=1)
    y = base_light()
    y.update({"name": name, "capacity": capacity})
    db.yards[y["id"]] = y
    return ok(ser_yard(y), status=201)


@app.route("/tow-yards", methods=["GET"])
def list_yards():
    auth(["PlatformAdmin", "EnforcementOfficer"])
    return paginate_and_serialize(list(db.yards.values()), ser_yard)


# ===========================================================================
# Scofflaw cases
# ===========================================================================
@app.route("/scofflaw-cases", methods=["POST"])
def create_case():
    auth(["PlatformAdmin", "EnforcementOfficer"])
    data = get_body()
    vehicle_id = req_str(data, "vehicle_id")
    veh = get_or_404(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    c = base_common()
    c.update({"vehicle_id": vehicle_id, "owner_id": veh["owner_id"],
              "case_status": "COMPLIANT", "hold_status": "NO_HOLD",
              "outstanding_count": 0, "assessed_balance_cents": 0,
              "collectible_balance_cents": 0, "eligible_for_boot": False,
              "eligible_for_tow": False})
    db.cases[c["id"]] = c
    recompute_case(c)
    return ok(ser_case(c), status=201)


@app.route("/scofflaw-cases/<rid>", methods=["GET"])
def get_case(rid):
    auth(ROLES)
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    recompute_case(c)
    return ok(ser_case(c))


@app.route("/scofflaw-cases", methods=["GET"])
def list_cases():
    auth(ROLES)
    items = list(db.cases.values())
    for c in items:
        recompute_case(c)
    vehicle_id = request.args.get("vehicle_id")
    owner_id = request.args.get("owner_id")
    case_status = request.args.get("case_status")
    if vehicle_id is not None:
        items = [x for x in items if x["vehicle_id"] == vehicle_id]
    if owner_id is not None:
        items = [x for x in items if x["owner_id"] == owner_id]
    if case_status is not None:
        items = [x for x in items if x["case_status"] == case_status]
    return paginate_and_serialize(items, ser_case)


@app.route("/scofflaw-cases/<rid>/place-hold", methods=["POST"])
def place_hold(rid):
    auth(["EnforcementOfficer"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    recompute_case(c)
    if c["case_status"] != "SCOFFLAW":
        err("ERR_CASE_NOT_SCOFFLAW", 409, "Case is not in SCOFFLAW status.")
    if c["hold_status"] == "HOLD_PLACED":
        err("ERR_HOLD_ALREADY_PLACED", 409, "A hold is already placed.")
    c["hold_status"] = "HOLD_PLACED"
    veh = db.vehicles.get(c["vehicle_id"])
    if veh is not None:
        veh["hold_flag"] = True
        bump(veh)
    bump(c)
    recompute_case(c)
    return ok(ser_case(c))


@app.route("/scofflaw-cases/<rid>/release-hold", methods=["POST"])
def release_hold(rid):
    auth(["CollectionsAdmin", "EnforcementOfficer"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    get_body()  # optional release_reason; ignored
    recompute_case(c)
    if c["hold_status"] != "HOLD_PLACED":
        err("ERR_NO_HOLD_TO_RELEASE", 409, "No active hold to release.")
    c["hold_status"] = "HOLD_RELEASED"
    veh = db.vehicles.get(c["vehicle_id"])
    if veh is not None:
        veh["hold_flag"] = False
        bump(veh)
    bump(c)
    recompute_case(c)
    return ok(ser_case(c))


# ===========================================================================
# Violations
# ===========================================================================
@app.route("/scofflaw-cases/<rid>/violations", methods=["POST"])
def file_violation(rid):
    auth(["EnforcementOfficer"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    data = get_body()
    citation_number = req_str(data, "citation_number")
    violation_type = req_enum(data, "violation_type", VIOLATION_TYPES)
    fine_amount_cents = req_int(data, "fine_amount_cents", minimum=0)
    issued_at = req_dt(data, "issued_at")
    due_at = req_dt(data, "due_at")
    for v in db.violations.values():
        if v["citation_number"] == citation_number:
            err("ERR_VALIDATION", 400, "citation_number must be unique.")
    v = base_common()
    v.update({"scofflaw_case_id": c["id"], "citation_number": citation_number,
              "violation_type": violation_type, "fine_amount_cents": fine_amount_cents,
              "issued_at": issued_at, "due_at": due_at, "late_penalty_cents": 0,
              "paid_amount_cents": 0, "credit_cents": 0, "status": "OUTSTANDING"})
    db.violations[v["id"]] = v
    bump(c)
    recompute_case(c)
    return ok(ser_violation(v), status=201)


@app.route("/violations/<rid>", methods=["GET"])
def get_violation(rid):
    auth(ROLES)
    v = get_or_404(db.violations, rid, "ERR_VIOLATION_NOT_FOUND")
    return ok(ser_violation(v))


@app.route("/violations", methods=["GET"])
def list_violations():
    auth(ROLES)
    items = list(db.violations.values())
    scofflaw_case_id = request.args.get("scofflaw_case_id")
    status = request.args.get("status")
    if scofflaw_case_id is not None:
        items = [x for x in items if x["scofflaw_case_id"] == scofflaw_case_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate_and_serialize(items, ser_violation)


# ===========================================================================
# Disputes
# ===========================================================================
@app.route("/violations/<rid>/disputes", methods=["POST"])
def file_dispute(rid):
    uid, role = auth(["Owner"])
    v = get_or_404(db.violations, rid, "ERR_VIOLATION_NOT_FOUND")
    c = db.cases[v["scofflaw_case_id"]]
    require_owner(c, uid, role)
    data = get_body()
    reason = req_str(data, "reason")
    # state
    if v["status"] != "OUTSTANDING":
        err("ERR_VIOLATION_NOT_OUTSTANDING", 409, "Violation is not OUTSTANDING.")
    # temporal window
    if clock() > parse_iso(v["issued_at"]) + timedelta(days=DISPUTE_WINDOW_DAYS):
        err("ERR_DISPUTE_WINDOW_EXPIRED", 422, "Dispute window has expired.")
    # one dispute per violation lifetime (any status)
    for d in db.disputes.values():
        if d["violation_id"] == v["id"]:
            err("ERR_DISPUTE_ALREADY_EXISTS", 409, "A dispute already exists for this violation.")
    d = base_common()
    d.update({"violation_id": v["id"], "officer_id": None, "reason": reason,
              "scheduled_start": None, "scheduled_end": None, "filed_at": now_ts(),
              "decided_at": None, "status": "SUBMITTED"})
    db.disputes[d["id"]] = d
    v["status"] = "DISPUTED"
    bump(v)
    bump(c)
    recompute_case(c)
    return ok(ser_dispute(d), status=201)


@app.route("/disputes/<rid>", methods=["GET"])
def get_dispute(rid):
    auth(ROLES)
    d = get_or_404(db.disputes, rid, "ERR_DISPUTE_NOT_FOUND")
    return ok(ser_dispute(d))


@app.route("/disputes", methods=["GET"])
def list_disputes():
    auth(ROLES)
    items = list(db.disputes.values())
    violation_id = request.args.get("violation_id")
    officer_id = request.args.get("officer_id")
    status = request.args.get("status")
    if violation_id is not None:
        items = [x for x in items if x["violation_id"] == violation_id]
    if officer_id is not None:
        items = [x for x in items if x["officer_id"] == officer_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate_and_serialize(items, ser_dispute)


def officer_double_booked(officer_id, start, end, exclude_id):
    s = parse_iso(start)
    e = parse_iso(end)
    for d in db.disputes.values():
        if d["id"] == exclude_id:
            continue
        if d["status"] != "SCHEDULED" or d["officer_id"] != officer_id:
            continue
        if intervals_overlap(s, e, parse_iso(d["scheduled_start"]), parse_iso(d["scheduled_end"])):
            return True
    return False


@app.route("/disputes/<rid>/schedule", methods=["POST"])
def schedule_dispute(rid):
    auth(["HearingClerk"])
    d = get_or_404(db.disputes, rid, "ERR_DISPUTE_NOT_FOUND")
    data = get_body()
    officer_id = req_str(data, "officer_id")
    scheduled_start = req_dt(data, "scheduled_start")
    scheduled_end = req_dt(data, "scheduled_end")
    get_or_404(db.officers, officer_id, "ERR_OFFICER_NOT_FOUND")
    if d["status"] in ("UPHELD", "DISMISSED", "WITHDRAWN"):
        err("ERR_TERMINAL_STATE", 409, "Dispute is in a terminal state.")
    if d["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Dispute is not SUBMITTED.")
    v = db.violations[d["violation_id"]]
    if v["status"] != "DISPUTED":
        err("ERR_INVALID_STATE", 409, "Linked violation is not DISPUTED.")
    if officer_double_booked(officer_id, scheduled_start, scheduled_end, d["id"]):
        err("ERR_OFFICER_DOUBLE_BOOKED", 409, "Officer is double-booked.")
    d["officer_id"] = officer_id
    d["scheduled_start"] = scheduled_start
    d["scheduled_end"] = scheduled_end
    d["status"] = "SCHEDULED"
    bump(d)
    return ok(ser_dispute(d))


@app.route("/disputes/<rid>/reschedule", methods=["POST"])
def reschedule_dispute(rid):
    auth(["HearingClerk"])
    d = get_or_404(db.disputes, rid, "ERR_DISPUTE_NOT_FOUND")
    data = get_body()
    scheduled_start = req_dt(data, "scheduled_start")
    scheduled_end = req_dt(data, "scheduled_end")
    if d["status"] in ("UPHELD", "DISMISSED", "WITHDRAWN"):
        err("ERR_TERMINAL_STATE", 409, "Dispute is in a terminal state.")
    if d["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Dispute is not SCHEDULED.")
    if officer_double_booked(d["officer_id"], scheduled_start, scheduled_end, d["id"]):
        err("ERR_OFFICER_DOUBLE_BOOKED", 409, "Officer is double-booked.")
    d["scheduled_start"] = scheduled_start
    d["scheduled_end"] = scheduled_end
    bump(d)
    return ok(ser_dispute(d))


@app.route("/disputes/<rid>/decide", methods=["POST"])
def decide_dispute(rid):
    auth(["HearingClerk"])
    d = get_or_404(db.disputes, rid, "ERR_DISPUTE_NOT_FOUND")
    data = get_body()
    decision = req_enum(data, "decision", DECISIONS)
    if d["status"] in ("UPHELD", "DISMISSED", "WITHDRAWN"):
        err("ERR_TERMINAL_STATE", 409, "Dispute is in a terminal state.")
    if d["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Dispute is not SCHEDULED.")
    v = db.violations[d["violation_id"]]
    c = db.cases[v["scofflaw_case_id"]]
    d["decided_at"] = now_ts()
    if decision == "UPHELD":
        d["status"] = "UPHELD"
        v["status"] = "VOIDED"
    else:
        d["status"] = "DISMISSED"
        v["status"] = "OUTSTANDING"
    bump(v)
    bump(d)
    bump(c)
    recompute_case(c)
    return ok(ser_dispute(d))


@app.route("/disputes/<rid>/withdraw", methods=["POST"])
def withdraw_dispute(rid):
    uid, role = auth(["Owner"])
    d = get_or_404(db.disputes, rid, "ERR_DISPUTE_NOT_FOUND")
    v = db.violations[d["violation_id"]]
    c = db.cases[v["scofflaw_case_id"]]
    require_owner(c, uid, role)
    get_body()
    if d["status"] in ("UPHELD", "DISMISSED", "WITHDRAWN"):
        err("ERR_TERMINAL_STATE", 409, "Dispute is in a terminal state.")
    if d["status"] not in ("SUBMITTED", "SCHEDULED"):
        err("ERR_INVALID_STATE", 409, "Dispute cannot be withdrawn.")
    d["status"] = "WITHDRAWN"
    if v["status"] == "DISPUTED":
        v["status"] = "OUTSTANDING"
        bump(v)
    bump(d)
    bump(c)
    recompute_case(c)
    return ok(ser_dispute(d))


# ===========================================================================
# Payments
# ===========================================================================
@app.route("/scofflaw-cases/<rid>/payments", methods=["POST"])
def create_payment(rid):
    uid, role = auth(["Owner"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    require_owner(c, uid, role)
    data = get_body()
    amount_cents = req_int(data, "amount_cents", minimum=1)
    method = req_enum(data, "method", PAYMENT_METHODS)
    recompute_case(c)
    # candidates: OUTSTANDING ordered by issued_at ASC, tie-break created_at ASC
    candidates = [v for v in violations_of(c) if v["status"] == "OUTSTANDING"]
    candidates.sort(key=lambda v: (parse_iso(v["issued_at"]), v["created_at"], v["_seq"]))
    total_due = sum(current_due(v) for v in candidates)
    if amount_cents > total_due:
        err("ERR_OVERPAYMENT", 422, "Payment exceeds collectible balance.")
    remaining = amount_cents
    allocation = []
    for v in candidates:
        if remaining <= 0:
            break
        due = current_due(v)
        applied = min(remaining, due)
        if applied <= 0:
            continue
        v["paid_amount_cents"] += applied
        remaining -= applied
        allocation.append({"violation_id": v["id"], "applied_cents": applied})
        if v["paid_amount_cents"] + v["credit_cents"] >= v["fine_amount_cents"] + late_penalty(v):
            v["status"] = "PAID"
        bump(v)
    p = base_light()
    p.update({"scofflaw_case_id": c["id"], "amount_cents": amount_cents, "method": method,
              "allocation": allocation, "applied_at": now_ts()})
    db.payments[p["id"]] = p
    bump(c)
    recompute_case(c)
    return ok(ser_payment(p), status=201)


@app.route("/payments/<rid>", methods=["GET"])
def get_payment(rid):
    auth(["PlatformAdmin", "EnforcementOfficer", "CollectionsAdmin", "Owner"])
    p = get_or_404(db.payments, rid, "ERR_PAYMENT_NOT_FOUND")
    return ok(ser_payment(p))


@app.route("/payments", methods=["GET"])
def list_payments():
    auth(["PlatformAdmin", "EnforcementOfficer", "CollectionsAdmin", "Owner"])
    items = list(db.payments.values())
    scofflaw_case_id = request.args.get("scofflaw_case_id")
    if scofflaw_case_id is not None:
        items = [x for x in items if x["scofflaw_case_id"] == scofflaw_case_id]
    return paginate_and_serialize(items, ser_payment)


# ===========================================================================
# Payment plans
# ===========================================================================
@app.route("/scofflaw-cases/<rid>/payment-plans", methods=["POST"])
def create_plan(rid):
    uid, role = auth(["Owner"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    require_owner(c, uid, role)
    data = get_body()
    expected_version = req_int(data, "expected_scofflaw_case_version")
    total_amount_cents = req_int(data, "total_amount_cents", minimum=1)
    installment_count = req_int(data, "installment_count")
    down_payment_cents = req_int(data, "down_payment_cents", minimum=0)
    # business: plan terms
    if installment_count < 1 or installment_count > PAYMENT_PLAN_MAX_INSTALLMENTS:
        err("ERR_INVALID_PLAN_TERMS", 422, "installment_count out of range.")
    if Decimal(down_payment_cents) < Decimal(total_amount_cents) * PAYMENT_PLAN_MIN_DOWN_PCT:
        err("ERR_INSUFFICIENT_DOWN_PAYMENT", 422, "Down payment too small.")
    # OCC (last)
    if expected_version != c["version"]:
        err("ERR_STALE_VERSION", 412, "Stale case version.")
    # supersede any prior ACTIVE/DEFAULTED plan on the case
    for p in db.plans.values():
        if p["scofflaw_case_id"] == c["id"] and p["status"] in ("ACTIVE", "DEFAULTED"):
            p["status"] = "CANCELLED"
            bump(p)
    installment_amount = rhu(Decimal(total_amount_cents - down_payment_cents) / Decimal(installment_count))
    p = base_common()
    p.update({"scofflaw_case_id": c["id"], "total_amount_cents": total_amount_cents,
              "installment_count": installment_count, "down_payment_cents": down_payment_cents,
              "installment_amount_cents": installment_amount,
              "paid_to_date_cents": down_payment_cents, "missed_count": 0, "status": "ACTIVE"})
    db.plans[p["id"]] = p
    bump(c)
    recompute_case(c)
    return ok(ser_plan(p), status=201)


@app.route("/payment-plans/<rid>", methods=["GET"])
def get_plan(rid):
    auth(["PlatformAdmin", "CollectionsAdmin", "Owner"])
    p = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    return ok(ser_plan(p))


@app.route("/payment-plans", methods=["GET"])
def list_plans():
    auth(["PlatformAdmin", "CollectionsAdmin", "Owner"])
    items = list(db.plans.values())
    scofflaw_case_id = request.args.get("scofflaw_case_id")
    status = request.args.get("status")
    if scofflaw_case_id is not None:
        items = [x for x in items if x["scofflaw_case_id"] == scofflaw_case_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate_and_serialize(items, ser_plan)


@app.route("/payment-plans/<rid>/record-installment", methods=["POST"])
def record_installment(rid):
    auth(["Owner"])
    p = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    data = get_body()
    amount_cents = req_int(data, "amount_cents", minimum=1)
    if p["status"] != "ACTIVE":
        err("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE.")
    p["paid_to_date_cents"] += amount_cents
    if p["paid_to_date_cents"] >= p["total_amount_cents"]:
        p["status"] = "COMPLETED"
    bump(p)
    return ok(ser_plan(p))


@app.route("/payment-plans/<rid>/default", methods=["POST"])
def default_plan(rid):
    auth(["CollectionsAdmin"])
    p = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    get_body()
    if p["status"] != "ACTIVE":
        err("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE.")
    p["status"] = "DEFAULTED"
    p["missed_count"] += 1
    bump(p)
    return ok(ser_plan(p))


@app.route("/payment-plans/<rid>/reinstate", methods=["POST"])
def reinstate_plan(rid):
    auth(["CollectionsAdmin"])
    p = get_or_404(db.plans, rid, "ERR_PLAN_NOT_FOUND")
    get_body()
    if p["status"] != "DEFAULTED":
        err("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not DEFAULTED.")
    p["status"] = "ACTIVE"
    bump(p)
    return ok(ser_plan(p))


# ===========================================================================
# Boot / tow orders
# ===========================================================================
@app.route("/scofflaw-cases/<rid>/boot-tow-orders", methods=["POST"])
def dispatch_order(rid):
    uid, role = auth(["EnforcementOfficer"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    data = get_body()
    expected_version = req_int(data, "expected_scofflaw_case_version")
    action_type = req_enum(data, "action_type", ACTION_TYPES)
    tow_yard_id = None
    stored_from = None
    stored_until = None
    if action_type == "TOW":
        tow_yard_id = req_str(data, "tow_yard_id")
        stored_from = req_dt(data, "stored_from")
        stored_until = req_dt(data, "stored_until")
    recompute_case(c)
    # tow yard existence (body-referenced)
    yard = None
    if action_type == "TOW":
        yard = get_or_404(db.yards, tow_yard_id, "ERR_TOW_YARD_NOT_FOUND")
    # state: case must be SCOFFLAW
    if c["case_status"] != "SCOFFLAW":
        err("ERR_CASE_NOT_SCOFFLAW", 409, "Case is not in SCOFFLAW status.")
    # capacity (before fiscal thresholds per §2.9)
    if action_type == "TOW":
        overlapping = 0
        s = parse_iso(stored_from)
        e = parse_iso(stored_until)
        for o in db.orders.values():
            if (o["tow_yard_id"] == tow_yard_id and o["action_type"] == "TOW"
                    and o["status"] in ("DISPATCHED", "APPLIED")):
                if intervals_overlap(s, e, parse_iso(o["stored_from"]), parse_iso(o["stored_until"])):
                    overlapping += 1
        if overlapping >= yard["capacity"]:
            err("ERR_TOW_YARD_FULL", 409, "Tow yard is at capacity for the interval.")
    # fiscal thresholds
    if action_type == "BOOT":
        if c["outstanding_count"] < BOOT_COUNT_THRESHOLD:
            err("ERR_BOOT_THRESHOLD_NOT_MET", 422, "Boot threshold not met.")
    else:
        if c["collectible_balance_cents"] < TOW_AMOUNT_THRESHOLD_CENTS:
            err("ERR_TOW_THRESHOLD_NOT_MET", 422, "Tow threshold not met.")
    # OCC (last)
    if expected_version != c["version"]:
        err("ERR_STALE_VERSION", 412, "Stale case version.")
    # supersede a still-DISPATCHED BOOT when dispatching a TOW
    if action_type == "TOW":
        for o in orders_of(c):
            if o["action_type"] == "BOOT" and o["status"] == "DISPATCHED":
                o["status"] = "CANCELLED"
                bump(o)
    o = base_common()
    o.update({"scofflaw_case_id": c["id"], "action_type": action_type, "tow_yard_id": tow_yard_id,
              "stored_from": stored_from, "stored_until": stored_until,
              "dispatched_by_user_id": uid, "applied_by_user_id": None,
              "release_fee_paid": False, "released_at": None, "status": "DISPATCHED"})
    db.orders[o["id"]] = o
    bump(c)
    recompute_case(c)
    return ok(ser_order(o), status=201)


@app.route("/boot-tow-orders/<rid>", methods=["GET"])
def get_order(rid):
    auth(["PlatformAdmin", "EnforcementOfficer", "Owner"])
    o = get_or_404(db.orders, rid, "ERR_ORDER_NOT_FOUND")
    return ok(ser_order(o))


@app.route("/boot-tow-orders", methods=["GET"])
def list_orders():
    auth(["PlatformAdmin", "EnforcementOfficer", "Owner"])
    items = list(db.orders.values())
    scofflaw_case_id = request.args.get("scofflaw_case_id")
    tow_yard_id = request.args.get("tow_yard_id")
    status = request.args.get("status")
    if scofflaw_case_id is not None:
        items = [x for x in items if x["scofflaw_case_id"] == scofflaw_case_id]
    if tow_yard_id is not None:
        items = [x for x in items if x["tow_yard_id"] == tow_yard_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate_and_serialize(items, ser_order)


@app.route("/boot-tow-orders/<rid>/apply", methods=["POST"])
def apply_order(rid):
    uid, role = auth(["EnforcementOfficer"])
    o = get_or_404(db.orders, rid, "ERR_ORDER_NOT_FOUND")
    get_body()
    if o["status"] != "DISPATCHED":
        err("ERR_ORDER_NOT_ACTIVE", 409, "Order is not DISPATCHED.")
    if uid == o["dispatched_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Applier must differ from dispatcher.")
    o["status"] = "APPLIED"
    o["applied_by_user_id"] = uid
    bump(o)
    return ok(ser_order(o))


@app.route("/boot-tow-orders/<rid>/pay-release-fee", methods=["POST"])
def pay_release_fee(rid):
    uid, role = auth(["Owner"])
    o = get_or_404(db.orders, rid, "ERR_ORDER_NOT_FOUND")
    c = db.cases[o["scofflaw_case_id"]]
    require_owner(c, uid, role)
    data = get_body()
    amount_cents = req_int(data, "amount_cents", minimum=1)
    if o["status"] in ("RELEASED", "CANCELLED"):
        err("ERR_TERMINAL_STATE", 409, "Order is in a terminal state.")
    if o["status"] != "APPLIED":
        err("ERR_ORDER_NOT_ACTIVE", 409, "Order is not APPLIED.")
    fee = order_release_fee(o)
    if amount_cents != fee:
        err("ERR_RELEASE_FEE_UNPAID", 409, "Amount must equal the current release fee.")
    o["release_fee_paid"] = True
    bump(o)
    return ok(ser_order(o))


@app.route("/boot-tow-orders/<rid>/release", methods=["POST"])
def release_order(rid):
    auth(["EnforcementOfficer"])
    o = get_or_404(db.orders, rid, "ERR_ORDER_NOT_FOUND")
    get_body()
    c = db.cases[o["scofflaw_case_id"]]
    if o["status"] != "APPLIED":
        err("ERR_ORDER_NOT_ACTIVE", 409, "Order is not APPLIED.")
    if not o["release_fee_paid"]:
        err("ERR_RELEASE_FEE_UNPAID", 409, "Release fee is unpaid.")
    recompute_case(c)
    if c["collectible_balance_cents"] != 0:
        err("ERR_BALANCE_OUTSTANDING", 409, "Case has an outstanding balance.")
    o["status"] = "RELEASED"
    o["released_at"] = now_ts()
    bump(o)
    recompute_case(c)
    return ok(ser_order(o))


@app.route("/boot-tow-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    auth(["EnforcementOfficer"])
    o = get_or_404(db.orders, rid, "ERR_ORDER_NOT_FOUND")
    get_body()
    c = db.cases[o["scofflaw_case_id"]]
    if o["status"] != "DISPATCHED":
        err("ERR_ORDER_NOT_ACTIVE", 409, "Order is not DISPATCHED.")
    o["status"] = "CANCELLED"
    bump(o)
    recompute_case(c)
    return ok(ser_order(o))


# ===========================================================================
# Hardship waivers
# ===========================================================================
@app.route("/scofflaw-cases/<rid>/hardship-waivers", methods=["POST"])
def request_waiver(rid):
    uid, role = auth(["Owner"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    require_owner(c, uid, role)
    data = get_body()
    hardship_tier = req_enum(data, "hardship_tier", HARDSHIP_TIERS)
    requested_amount_cents = req_int(data, "requested_amount_cents", minimum=0)
    w = base_common()
    w.update({"scofflaw_case_id": c["id"], "hardship_tier": hardship_tier,
              "requested_amount_cents": requested_amount_cents, "approved_amount_cents": 0,
              "decided_at": None, "status": "REQUESTED"})
    db.waivers[w["id"]] = w
    return ok(ser_waiver(w), status=201)


@app.route("/hardship-waivers/<rid>", methods=["GET"])
def get_waiver(rid):
    auth(["PlatformAdmin", "CollectionsAdmin", "Owner"])
    w = get_or_404(db.waivers, rid, "ERR_WAIVER_NOT_FOUND")
    return ok(ser_waiver(w))


@app.route("/hardship-waivers", methods=["GET"])
def list_waivers():
    auth(["PlatformAdmin", "CollectionsAdmin", "Owner"])
    items = list(db.waivers.values())
    scofflaw_case_id = request.args.get("scofflaw_case_id")
    status = request.args.get("status")
    if scofflaw_case_id is not None:
        items = [x for x in items if x["scofflaw_case_id"] == scofflaw_case_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate_and_serialize(items, ser_waiver)


@app.route("/hardship-waivers/<rid>/decide", methods=["POST"])
def decide_waiver(rid):
    auth(["CollectionsAdmin"])
    w = get_or_404(db.waivers, rid, "ERR_WAIVER_NOT_FOUND")
    data = get_body()
    approve = req_bool(data, "approve")
    if w["status"] in ("APPROVED", "DENIED"):
        err("ERR_TERMINAL_STATE", 409, "Waiver is in a terminal state.")
    if w["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Waiver is not REQUESTED.")
    c = db.cases[w["scofflaw_case_id"]]
    w["decided_at"] = now_ts()
    if not approve:
        w["status"] = "DENIED"
        bump(w)
        return ok(ser_waiver(w))
    # approve
    outstanding = [v for v in violations_of(c) if v["status"] == "OUTSTANDING"]
    if w["hardship_tier"] == "TIER_2":
        approved = sum(current_due(v) for v in outstanding)
        for v in outstanding:
            v["status"] = "WAIVED"
            bump(v)
    else:  # TIER_1
        approved = 0
        for v in outstanding:
            credit = rhu(Decimal(current_due(v)) * HARDSHIP_TIER_1_PCT)
            v["credit_cents"] += credit
            approved += credit
            bump(v)
    w["approved_amount_cents"] = approved
    w["status"] = "APPROVED"
    bump(w)
    bump(c)
    recompute_case(c)
    return ok(ser_waiver(w))


# ===========================================================================
# Collections referrals
# ===========================================================================
@app.route("/scofflaw-cases/<rid>/collections-referrals", methods=["POST"])
def create_referral(rid):
    auth(["CollectionsAdmin"])
    c = get_or_404(db.cases, rid, "ERR_CASE_NOT_FOUND")
    data = get_body()
    agency_name = req_str(data, "agency_name")
    recompute_case(c)
    # state: case must be SCOFFLAW
    if c["case_status"] != "SCOFFLAW":
        err("ERR_INVALID_STATE", 409, "Case is not in SCOFFLAW status.")
    # temporal: oldest OUTSTANDING violation aged >= COLLECTIONS_MIN_AGE_DAYS
    outstanding = [v for v in violations_of(c) if v["status"] == "OUTSTANDING"]
    if not outstanding:
        err("ERR_NOT_YET_REFERABLE", 422, "No referable outstanding violations.")
    oldest = min(parse_iso(v["issued_at"]) for v in outstanding)
    if clock() - oldest < timedelta(days=COLLECTIONS_MIN_AGE_DAYS):
        err("ERR_NOT_YET_REFERABLE", 422, "Oldest violation is not yet old enough.")
    # constraint: no active REFERRED referral on the case
    for r in db.referrals.values():
        if r["scofflaw_case_id"] == c["id"] and r["status"] == "REFERRED":
            err("ERR_REFERRAL_ALREADY_EXISTS", 409, "An active referral already exists.")
    referred_amount = c["collectible_balance_cents"]
    r = base_common()
    r.update({"scofflaw_case_id": c["id"], "agency_name": agency_name,
              "referred_amount_cents": referred_amount, "settled_amount_cents": 0,
              "referred_at": now_ts(), "status": "REFERRED"})
    db.referrals[r["id"]] = r
    for v in outstanding:
        v["status"] = "IN_COLLECTIONS"
        bump(v)
    bump(c)
    recompute_case(c)
    return ok(ser_referral(r), status=201)


@app.route("/collections-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    auth(["PlatformAdmin", "CollectionsAdmin", "Owner"])
    r = get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    return ok(ser_referral(r))


@app.route("/collections-referrals", methods=["GET"])
def list_referrals():
    auth(["PlatformAdmin", "CollectionsAdmin", "Owner"])
    items = list(db.referrals.values())
    scofflaw_case_id = request.args.get("scofflaw_case_id")
    status = request.args.get("status")
    if scofflaw_case_id is not None:
        items = [x for x in items if x["scofflaw_case_id"] == scofflaw_case_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return paginate_and_serialize(items, ser_referral)


@app.route("/collections-referrals/<rid>/recall", methods=["POST"])
def recall_referral(rid):
    auth(["CollectionsAdmin"])
    r = get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    get_body()
    c = db.cases[r["scofflaw_case_id"]]
    if r["status"] in ("RECALLED", "SETTLED"):
        err("ERR_TERMINAL_STATE", 409, "Referral is in a terminal state.")
    if r["status"] != "REFERRED":
        err("ERR_INVALID_STATE", 409, "Referral is not REFERRED.")
    r["status"] = "RECALLED"
    for v in violations_of(c):
        if v["status"] == "IN_COLLECTIONS":
            v["status"] = "OUTSTANDING"
            bump(v)
    bump(r)
    bump(c)
    recompute_case(c)
    return ok(ser_referral(r))


@app.route("/collections-referrals/<rid>/settle", methods=["POST"])
def settle_referral(rid):
    auth(["CollectionsAdmin"])
    r = get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    data = get_body()
    settled_amount_cents = req_int(data, "settled_amount_cents", minimum=0)
    c = db.cases[r["scofflaw_case_id"]]
    if r["status"] in ("RECALLED", "SETTLED"):
        err("ERR_TERMINAL_STATE", 409, "Referral is in a terminal state.")
    if r["status"] != "REFERRED":
        err("ERR_INVALID_STATE", 409, "Referral is not REFERRED.")
    r["status"] = "SETTLED"
    r["settled_amount_cents"] = settled_amount_cents
    for v in violations_of(c):
        if v["status"] == "IN_COLLECTIONS":
            v["status"] = "PAID"
            bump(v)
    bump(r)
    bump(c)
    recompute_case(c)
    return ok(ser_referral(r))


# ===========================================================================
# Reporting
# ===========================================================================
@app.route("/reports/scofflaw-summary", methods=["GET"])
def scofflaw_summary():
    auth(["PlatformAdmin", "CollectionsAdmin"])
    cases = list(db.cases.values())
    for c in cases:
        recompute_case(c)
    case_status = request.args.get("case_status")
    if case_status is not None:
        cases = [c for c in cases if c["case_status"] == case_status]
    report = {
        "total_cases": len(cases),
        "scofflaw_cases": sum(1 for c in cases if c["case_status"] == "SCOFFLAW"),
        "resolved_cases": sum(1 for c in cases if c["case_status"] == "RESOLVED"),
        "total_collectible_cents": sum(c["collectible_balance_cents"] for c in cases),
        "total_assessed_cents": sum(c["assessed_balance_cents"] for c in cases),
        "holds_placed": sum(1 for c in cases if c["hold_status"] == "HOLD_PLACED"),
    }
    return ok(report, response_type="object")


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
def reset_state():
    global db
    db = DB()
    STATE["clock"] = parse_iso(DEFAULT_CLOCK)


reset_state()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
