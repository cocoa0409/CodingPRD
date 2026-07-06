import os
import math
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Customer", "Technician", "Dispatcher", "ServiceAdmin"}

LABOR_QUARTER_CENTS = 3000
DIAGNOSTIC_FEE_CENTS = 8900
WAIVER_THRESHOLD_CENTS = 15000
W_AGE = 5
W_REPAIR = 8
W_RECALL = 20
TRAVEL_BUFFER = timedelta(minutes=30)

SR_TERMINAL = {"COMPLETED", "DECLINED", "SAFETY_HOLD"}

# ---------------------------------------------------------------------------
# In-memory storage (empty on every boot; NO seeding)
# ---------------------------------------------------------------------------
DB = {
    "customers": {},
    "appliances": {},
    "warranty_contracts": {},
    "parts": {},
    "technicians": {},
    "truck_stock": {},
    "service_zones": {},
    "service_requests": {},
    "appointments": {},
    "estimates": {},
    "parts_orders": {},
    "payments": {},
    "recalls": {},
}
_seq = itertools.count(1)


# ---------------------------------------------------------------------------
# Errors / envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def err_response(error_id, message, http):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), http


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.message, e.http)


@app.errorhandler(404)
def _handle_404(e):
    return err_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return err_response("ERR_NOT_FOUND", "Method not allowed", 405)


@app.errorhandler(Exception)
def _handle_uncaught(e):
    if isinstance(e, ApiError):
        return err_response(e.error_id, e.message, e.http)
    return err_response("ERR_VALIDATION", str(e), 400)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(**fields):
    ts = now_iso()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }
    e.update(fields)
    return e


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] += 1


def get_or_404(coll, _id):
    e = DB[coll].get(_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{coll[:-1]} not found")
    return e


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.before_request
def _authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    g.uid = uid
    g.role = role


def require_role(*allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return b


def require(b, *names):
    for n in names:
        if n not in b or b[n] is None:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {n}")


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be an integer")
    return v


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime format")


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid date format")


# ---------------------------------------------------------------------------
# Listing / pagination
# ---------------------------------------------------------------------------
def paginate(items, filters=None):
    if filters:
        for field, val in filters.items():
            if val is not None:
                items = [it for it in items if str(it.get(field)) == str(val)]
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)

    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
        offset = int(offset)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid pagination parameter")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    page = items[offset:offset + limit]
    data = [serialize(it) for it in page]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok(data, 200, "array", meta_extra)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def labor_cost(tasks):
    total = 0
    for t in tasks:
        if not isinstance(t, dict) or "minutes" not in t:
            raise ApiError("ERR_VALIDATION", 400, "Invalid labor task")
        minutes = as_int(t["minutes"], "minutes")
        if minutes < 0:
            raise ApiError("ERR_VALIDATION", 400, "minutes must be >= 0")
        quarters = math.ceil(minutes / 15) if minutes > 0 else 0
        total += quarters * LABOR_QUARTER_CENTS
    return total


def parts_total(required_parts):
    total = 0
    for line in required_parts:
        part = get_or_404("parts", line["part_id"])
        total += part["unit_price_cents"] * line["quantity"]
    return total


def validate_required_parts(required_parts):
    if not isinstance(required_parts, list):
        raise ApiError("ERR_VALIDATION", 400, "required_parts must be an array")
    for line in required_parts:
        if not isinstance(line, dict) or "part_id" not in line or "quantity" not in line:
            raise ApiError("ERR_VALIDATION", 400, "Invalid required_parts line")
        as_int(line["quantity"], "quantity")
        if line["quantity"] < 0:
            raise ApiError("ERR_VALIDATION", 400, "quantity must be >= 0")


def validate_labor_tasks(tasks):
    if not isinstance(tasks, list):
        raise ApiError("ERR_VALIDATION", 400, "labor_tasks must be an array")
    for t in tasks:
        if not isinstance(t, dict) or "minutes" not in t:
            raise ApiError("ERR_VALIDATION", 400, "Invalid labor task")


def find_truck_stock(tech_id, part_id):
    for ts in DB["truck_stock"].values():
        if ts["technician_id"] == tech_id and ts["part_id"] == part_id:
            return ts
    return None


def recompute_truck(ts):
    ts["quantity_available"] = ts["quantity_on_hand"] - ts["quantity_reserved"]


def recompute_contract(c):
    c["remaining_coverage_cents"] = c["coverage_cap_cents"] - c["claimed_cents"]


def current_booked_appointment(sr_id):
    for a in DB["appointments"].values():
        if a["service_request_id"] == sr_id and a["status"] == "BOOKED":
            return a
    return None


def find_approved_estimate(sr_id):
    for e in DB["estimates"].values():
        if e["service_request_id"] == sr_id and e["status"] == "APPROVED":
            return e
    return None


def find_pending_estimate(sr_id):
    for e in DB["estimates"].values():
        if e["service_request_id"] == sr_id and e["status"] == "PENDING_APPROVAL":
            return e
    return None


def any_estimate_exists(sr_id):
    return any(e["service_request_id"] == sr_id for e in DB["estimates"].values())


def matching_active_recall(brand, model, exclude_id=None):
    for r in DB["recalls"].values():
        if r["id"] == exclude_id:
            continue
        if r["status"] == "ACTIVE" and r["brand"] == brand and r["model"] == model:
            return True
    return False


def compute_health(appliance, service_date, prior_repairs):
    pd = parse_date(appliance["purchase_date"])
    days = (service_date - pd).days
    age_years = math.floor(days / 365)
    recalled = appliance["recall_status"] == "RECALLED"
    raw = 100 - age_years * W_AGE - prior_repairs * W_REPAIR - (W_RECALL if recalled else 0)
    return max(0, min(100, raw))


def recompute_appliance_health(appliance):
    sd = appliance["_hs_service_date"]
    prior = appliance["_hs_prior_repairs"]
    appliance["health_score"] = compute_health(appliance, sd, prior)


def warranty_split(subtotal, contract, routing, recall_applies, diagnostic_effective):
    """Returns (warranty_covered_cents, customer_responsibility_cents)."""
    cap_remaining = (contract["coverage_cap_cents"] - contract["claimed_cents"]) if contract else 0
    if recall_applies:
        return 0, 0
    if routing == "NONE":
        return 0, subtotal + diagnostic_effective
    if routing == "MANUFACTURER":
        covered = min(subtotal, cap_remaining)
        return covered, subtotal - covered
    # EXTENDED / HOME_WARRANTY
    covered = min(subtotal, cap_remaining)
    deductible = contract["deductible_cents"] if contract else 0
    return covered, deductible + (subtotal - covered)


def diagnostic_effective(routing, subtotal, completed):
    if routing != "NONE":
        return 0
    if completed and subtotal >= WAIVER_THRESHOLD_CENTS:
        return 0
    return DIAGNOSTIC_FEE_CENTS


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    require_role("ServiceAdmin")
    b = body()
    require(b, "full_name", "email", "phone", "address")
    c = new_entity(
        full_name=b["full_name"], email=b["email"], phone=b["phone"], address=b["address"]
    )
    DB["customers"][c["id"]] = c
    return ok(serialize(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    return ok(serialize(get_or_404("customers", cid)))


# ---------------------------------------------------------------------------
# Appliance
# ---------------------------------------------------------------------------
@app.route("/appliances", methods=["POST"])
def create_appliance():
    require_role("Customer", "ServiceAdmin")
    b = body()
    require(b, "customer_id", "brand", "model", "serial_number", "purchase_date")
    get_or_404("customers", b["customer_id"])
    parse_date(b["purchase_date"])
    recalled = matching_active_recall(b["brand"], b["model"])
    a = new_entity(
        customer_id=b["customer_id"],
        brand=b["brand"],
        model=b["model"],
        serial_number=b["serial_number"],
        purchase_date=b["purchase_date"],
        recall_status="RECALLED" if recalled else "CLEAR",
        completed_repair_count=0,
        health_score=0,
    )
    a["_hs_service_date"] = parse_date(b["purchase_date"])
    a["_hs_prior_repairs"] = 0
    recompute_appliance_health(a)
    DB["appliances"][a["id"]] = a
    return ok(serialize(a), 201)


@app.route("/appliances/<aid>", methods=["GET"])
def get_appliance(aid):
    return ok(serialize(get_or_404("appliances", aid)))


@app.route("/appliances", methods=["GET"])
def list_appliances():
    return paginate(
        list(DB["appliances"].values()),
        {"customer_id": request.args.get("customer_id")},
    )


# ---------------------------------------------------------------------------
# WarrantyContract
# ---------------------------------------------------------------------------
@app.route("/warranty-contracts", methods=["POST"])
def create_warranty():
    require_role("ServiceAdmin")
    b = body()
    require(b, "appliance_id", "coverage_type", "coverage_start", "coverage_end", "coverage_cap_cents")
    get_or_404("appliances", b["appliance_id"])
    coverage_type = b["coverage_type"]
    if coverage_type not in ("MANUFACTURER", "EXTENDED", "HOME_WARRANTY"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid coverage_type")
    parse_date(b["coverage_start"])
    parse_date(b["coverage_end"])
    deductible = b.get("deductible_cents", 0)
    if deductible is None:
        deductible = 0
    as_int(deductible, "deductible_cents")
    cap = as_int(b["coverage_cap_cents"], "coverage_cap_cents")
    if coverage_type == "MANUFACTURER" and deductible != 0:
        raise ApiError("ERR_VALIDATION", 400, "deductible_cents must be 0 for MANUFACTURER")
    c = new_entity(
        appliance_id=b["appliance_id"],
        coverage_type=coverage_type,
        coverage_start=b["coverage_start"],
        coverage_end=b["coverage_end"],
        deductible_cents=deductible,
        coverage_cap_cents=cap,
        claimed_cents=0,
        remaining_coverage_cents=cap,
    )
    DB["warranty_contracts"][c["id"]] = c
    return ok(serialize(c), 201)


@app.route("/warranty-contracts/<wid>", methods=["GET"])
def get_warranty(wid):
    return ok(serialize(get_or_404("warranty_contracts", wid)))


@app.route("/warranty-contracts", methods=["GET"])
def list_warranty():
    return paginate(
        list(DB["warranty_contracts"].values()),
        {"appliance_id": request.args.get("appliance_id")},
    )


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------
@app.route("/parts", methods=["POST"])
def create_part():
    require_role("ServiceAdmin")
    b = body()
    require(b, "part_number", "name", "unit_price_cents")
    as_int(b["unit_price_cents"], "unit_price_cents")
    p = new_entity(
        part_number=b["part_number"], name=b["name"], unit_price_cents=b["unit_price_cents"]
    )
    DB["parts"][p["id"]] = p
    return ok(serialize(p), 201)


# ---------------------------------------------------------------------------
# Technician
# ---------------------------------------------------------------------------
@app.route("/technicians", methods=["POST"])
def create_technician():
    require_role("ServiceAdmin")
    b = body()
    require(b, "full_name")
    t = new_entity(full_name=b["full_name"], status="ON_DUTY")
    DB["technicians"][t["id"]] = t
    return ok(serialize(t), 201)


@app.route("/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    return ok(serialize(get_or_404("technicians", tid)))


@app.route("/technicians/<tid>/status", methods=["POST"])
def technician_status(tid):
    require_role("Technician", "ServiceAdmin")
    b = body()
    require(b, "to_status")
    t = get_or_404("technicians", tid)
    to_status = b["to_status"]
    if to_status not in ("ON_DUTY", "OFF_DUTY"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_status")
    # state (priority 4)
    valid = (t["status"] == "ON_DUTY" and to_status == "OFF_DUTY") or (
        t["status"] == "OFF_DUTY" and to_status == "ON_DUTY"
    )
    if not valid:
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid technician status transition")
    # ownership (priority 6)
    if g.role == "Technician" and g.uid != tid:
        raise ApiError("ERR_NOT_OWNER", 403, "Technician may only toggle their own status")
    t["status"] = to_status
    touch(t)
    return ok(serialize(t))


# ---------------------------------------------------------------------------
# TruckStockItem
# ---------------------------------------------------------------------------
@app.route("/truck-stock", methods=["POST"])
def create_truck_stock():
    require_role("Technician", "ServiceAdmin")
    b = body()
    require(b, "technician_id", "part_id", "quantity_on_hand")
    get_or_404("technicians", b["technician_id"])
    get_or_404("parts", b["part_id"])
    qty = as_int(b["quantity_on_hand"], "quantity_on_hand")
    if qty < 0:
        raise ApiError("ERR_VALIDATION", 400, "quantity_on_hand must be >= 0")
    # ownership (priority 6)
    if g.role == "Technician" and g.uid != b["technician_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Technician may only manage own truck stock")
    # uniqueness (priority 12)
    if find_truck_stock(b["technician_id"], b["part_id"]) is not None:
        raise ApiError("ERR_DUPLICATE_TRUCK_STOCK", 409, "Truck stock line already exists")
    ts = new_entity(
        technician_id=b["technician_id"],
        part_id=b["part_id"],
        quantity_on_hand=qty,
        quantity_reserved=0,
        quantity_available=qty,
    )
    DB["truck_stock"][ts["id"]] = ts
    return ok(serialize(ts), 201)


@app.route("/truck-stock/<sid>", methods=["GET"])
def get_truck_stock(sid):
    return ok(serialize(get_or_404("truck_stock", sid)))


@app.route("/truck-stock", methods=["GET"])
def list_truck_stock():
    return paginate(
        list(DB["truck_stock"].values()),
        {
            "technician_id": request.args.get("technician_id"),
            "part_id": request.args.get("part_id"),
        },
    )


# ---------------------------------------------------------------------------
# ServiceZone
# ---------------------------------------------------------------------------
@app.route("/service-zones", methods=["POST"])
def create_zone():
    require_role("ServiceAdmin", "Dispatcher")
    b = body()
    require(b, "name", "max_concurrent_appointments")
    cap = as_int(b["max_concurrent_appointments"], "max_concurrent_appointments")
    z = new_entity(name=b["name"], max_concurrent_appointments=cap)
    DB["service_zones"][z["id"]] = z
    return ok(serialize(z), 201)


# ---------------------------------------------------------------------------
# ServiceRequest
# ---------------------------------------------------------------------------
@app.route("/service-requests", methods=["POST"])
def create_service_request():
    require_role("Customer", "ServiceAdmin")
    b = body()
    require(b, "customer_id", "appliance_id", "reported_issue")
    get_or_404("customers", b["customer_id"])
    get_or_404("appliances", b["appliance_id"])
    sr = new_entity(
        customer_id=b["customer_id"],
        appliance_id=b["appliance_id"],
        assigned_technician_id=None,
        covering_contract_id=None,
        reported_issue=b["reported_issue"],
        status="INTAKE",
        warranty_routing=None,
        diagnostic_fee_cents=0,
        health_score_at_diagnosis=None,
        final_parts_total_cents=0,
        final_labor_total_cents=0,
        final_repair_subtotal_cents=0,
        warranty_covered_cents=0,
        customer_responsibility_cents=0,
        amount_due_cents=0,
        visit_count=0,
    )
    DB["service_requests"][sr["id"]] = sr
    return ok(serialize(sr), 201)


@app.route("/service-requests/<sid>", methods=["GET"])
def get_service_request(sid):
    return ok(serialize(get_or_404("service_requests", sid)))


@app.route("/service-requests", methods=["GET"])
def list_service_requests():
    return paginate(
        list(DB["service_requests"].values()),
        {
            "customer_id": request.args.get("customer_id"),
            "appliance_id": request.args.get("appliance_id"),
            "assigned_technician_id": request.args.get("assigned_technician_id"),
            "covering_contract_id": request.args.get("covering_contract_id"),
            "status": request.args.get("status"),
        },
    )


def tech_timeline_conflict(tech_id, start, end, exclude_appt_id=None):
    for a in DB["appointments"].values():
        if a["status"] != "BOOKED" or a["technician_id"] != tech_id:
            continue
        if a["id"] == exclude_appt_id:
            continue
        es = parse_dt(a["window_start"])
        ee = parse_dt(a["window_end"])
        if start < ee + TRAVEL_BUFFER and es < end + TRAVEL_BUFFER:
            return True
    return False


def zone_overlap_count(zone_id, start, end):
    count = 0
    for a in DB["appointments"].values():
        if a["status"] != "BOOKED" or a["zone_id"] != zone_id:
            continue
        es = parse_dt(a["window_start"])
        ee = parse_dt(a["window_end"])
        if start < ee and es < end:
            count += 1
    return count


@app.route("/service-requests/<sid>/appointments", methods=["POST"])
def book_appointment(sid):
    require_role("Dispatcher", "ServiceAdmin")
    b = body()
    require(b, "technician_id", "zone_id", "window_start", "window_end")
    sr = get_or_404("service_requests", sid)
    tech = get_or_404("technicians", b["technician_id"])
    zone = get_or_404("service_zones", b["zone_id"])
    start = parse_dt(b["window_start"])
    end = parse_dt(b["window_end"])
    if not (end > start):
        raise ApiError("ERR_VALIDATION", 400, "window_end must be after window_start")
    # state (priority 4)
    if sr["status"] not in ("INTAKE", "AWAITING_PARTS"):
        raise ApiError("ERR_INVALID_STATE", 409, "Request not schedulable in current state")
    appliance = get_or_404("appliances", sr["appliance_id"])
    # safety (priority 7)
    if appliance["recall_status"] == "RECALLED":
        raise ApiError("ERR_SAFETY_RECALL_HOLD", 409, "Appliance under active recall")
    # technician on-duty (priority 8)
    if tech["status"] != "ON_DUTY":
        raise ApiError("ERR_TECHNICIAN_OFF_DUTY", 409, "Technician is off duty")
    # parts ready (priority 9) — only from AWAITING_PARTS
    if sr["status"] == "AWAITING_PARTS":
        pos = [p for p in DB["parts_orders"].values() if p["service_request_id"] == sid]
        if any(p["status"] != "RECEIVED" for p in pos):
            raise ApiError("ERR_PARTS_NOT_READY", 409, "All parts orders must be received")
    # tech timeline (priority 10)
    if tech_timeline_conflict(b["technician_id"], start, end):
        raise ApiError("ERR_TECH_DOUBLE_BOOKED", 409, "Technician has a timeline conflict")
    # zone capacity (priority 11)
    if zone_overlap_count(b["zone_id"], start, end) + 1 > zone["max_concurrent_appointments"]:
        raise ApiError("ERR_ZONE_CAPACITY_EXCEEDED", 409, "Zone capacity exceeded")

    appt = new_entity(
        service_request_id=sid,
        technician_id=b["technician_id"],
        zone_id=b["zone_id"],
        window_start=b["window_start"],
        window_end=b["window_end"],
        status="BOOKED",
    )
    DB["appointments"][appt["id"]] = appt
    sr["assigned_technician_id"] = appt["technician_id"]
    sr["visit_count"] += 1
    sr["status"] = "SCHEDULED"
    touch(sr)
    return ok(serialize(appt), 201)


@app.route("/service-requests/<sid>/diagnose", methods=["POST"])
def diagnose(sid):
    require_role("Technician")
    b = body()
    require(b, "labor_tasks", "required_parts")
    sr = get_or_404("service_requests", sid)
    validate_labor_tasks(b["labor_tasks"])
    validate_required_parts(b["required_parts"])
    # state (priority 4)
    if sr["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request not in SCHEDULED state")
    if any_estimate_exists(sid):
        raise ApiError("ERR_INVALID_STATE", 409, "An estimate already exists")
    # ownership (priority 6)
    if g.uid != sr["assigned_technician_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Only the assigned technician may diagnose")
    appliance = get_or_404("appliances", sr["appliance_id"])
    # safety (priority 7)
    if appliance["recall_status"] == "RECALLED":
        raise ApiError("ERR_SAFETY_RECALL_HOLD", 409, "Appliance under active recall")
    # existence of referenced parts
    for line in b["required_parts"]:
        get_or_404("parts", line["part_id"])

    appt = current_booked_appointment(sid)
    service_dt = parse_dt(appt["window_start"]).date() if appt else datetime.now(timezone.utc).date()

    # warranty contract selection
    routing, contract = select_warranty_contract(sr["appliance_id"], service_dt)
    sr["warranty_routing"] = routing
    sr["covering_contract_id"] = contract["id"] if contract else None
    sr["diagnostic_fee_cents"] = DIAGNOSTIC_FEE_CENTS if routing == "NONE" else 0

    # health at diagnosis (excludes current in-flight request)
    prior = count_completed_for_appliance(sr["appliance_id"])
    sr["health_score_at_diagnosis"] = compute_health(appliance, service_dt, prior)
    sr["_service_date"] = service_dt.isoformat()

    # estimate amounts
    est_parts = parts_total(b["required_parts"])
    est_labor = labor_cost(b["labor_tasks"])
    est_subtotal = est_parts + est_labor
    est_diag = diagnostic_effective(routing, est_subtotal, completed=False)
    recall_applies = appliance["recall_status"] == "RECALLED"
    _covered, cust_resp = warranty_split(est_subtotal, contract, routing, recall_applies, est_diag)

    est = new_entity(
        service_request_id=sid,
        labor_tasks=b["labor_tasks"],
        required_parts=b["required_parts"],
        estimated_parts_total_cents=est_parts,
        estimated_labor_total_cents=est_labor,
        estimated_repair_subtotal_cents=est_subtotal,
        estimated_diagnostic_fee_cents=est_diag,
        estimated_total_cents=est_subtotal + est_diag,
        estimated_customer_responsibility_cents=cust_resp,
        status="PENDING_APPROVAL",
    )
    DB["estimates"][est["id"]] = est

    if appt:
        appt["status"] = "COMPLETED"
        touch(appt)
    sr["status"] = "DIAGNOSED"
    touch(sr)
    return ok(serialize(est), 201)


def count_completed_for_appliance(appliance_id):
    return sum(
        1
        for r in DB["service_requests"].values()
        if r["appliance_id"] == appliance_id and r["status"] == "COMPLETED"
    )


def select_warranty_contract(appliance_id, service_date):
    candidates = []
    for c in DB["warranty_contracts"].values():
        if c["appliance_id"] != appliance_id:
            continue
        cs = parse_date(c["coverage_start"])
        ce = parse_date(c["coverage_end"])
        if cs <= service_date <= ce:
            candidates.append(c)
    if not candidates:
        return "NONE", None
    rank = {"MANUFACTURER": 0, "EXTENDED": 1, "HOME_WARRANTY": 2}
    candidates.sort(key=lambda c: (rank[c["coverage_type"]], c["_seq"]))
    best = candidates[0]
    return best["coverage_type"], best


@app.route("/service-requests/<sid>/estimates", methods=["POST"])
def revise_estimate(sid):
    require_role("Technician")
    b = body()
    require(b, "labor_tasks", "required_parts", "expected_service_request_version")
    sr = get_or_404("service_requests", sid)
    validate_labor_tasks(b["labor_tasks"])
    validate_required_parts(b["required_parts"])
    as_int(b["expected_service_request_version"], "expected_service_request_version")
    # state (priority 4)
    if sr["status"] != "DIAGNOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request not in DIAGNOSED state")
    prior = find_pending_estimate(sid)
    if prior is None:
        raise ApiError("ERR_INVALID_STATE", 409, "No pending estimate to revise")
    # ownership (priority 6)
    if g.uid != sr["assigned_technician_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Only the assigned technician may revise")
    # existence of referenced parts
    for line in b["required_parts"]:
        get_or_404("parts", line["part_id"])
    # OCC (priority 15)
    if b["expected_service_request_version"] != sr["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Service request version mismatch")

    appliance = get_or_404("appliances", sr["appliance_id"])
    service_dt = parse_date(sr["_service_date"]) if sr.get("_service_date") else datetime.now(timezone.utc).date()
    routing = sr["warranty_routing"]
    contract = DB["warranty_contracts"].get(sr["covering_contract_id"]) if sr["covering_contract_id"] else None

    est_parts = parts_total(b["required_parts"])
    est_labor = labor_cost(b["labor_tasks"])
    est_subtotal = est_parts + est_labor
    est_diag = diagnostic_effective(routing, est_subtotal, completed=False)
    recall_applies = appliance["recall_status"] == "RECALLED"
    _covered, cust_resp = warranty_split(est_subtotal, contract, routing, recall_applies, est_diag)

    prior["status"] = "SUPERSEDED"
    touch(prior)
    est = new_entity(
        service_request_id=sid,
        labor_tasks=b["labor_tasks"],
        required_parts=b["required_parts"],
        estimated_parts_total_cents=est_parts,
        estimated_labor_total_cents=est_labor,
        estimated_repair_subtotal_cents=est_subtotal,
        estimated_diagnostic_fee_cents=est_diag,
        estimated_total_cents=est_subtotal + est_diag,
        estimated_customer_responsibility_cents=cust_resp,
        status="PENDING_APPROVAL",
    )
    DB["estimates"][est["id"]] = est
    touch(sr)  # version += 1
    return ok(serialize(est), 201)


@app.route("/service-requests/<sid>/complete", methods=["POST"])
def complete_request(sid):
    require_role("Technician")
    b = body()
    require(b, "actual_labor_tasks")
    sr = get_or_404("service_requests", sid)
    validate_labor_tasks(b["actual_labor_tasks"])
    # state (priority 4)
    approved_est = find_approved_estimate(sid)
    if sr["status"] == "APPROVED":
        pass
    elif sr["status"] == "SCHEDULED":
        if approved_est is None:
            raise ApiError("ERR_INVALID_STATE", 409, "No approved estimate for callback completion")
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Request not completable in current state")
    # ownership (priority 6)
    if g.uid != sr["assigned_technician_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Only the assigned technician may complete")
    appliance = get_or_404("appliances", sr["appliance_id"])
    # safety (priority 7)
    if appliance["recall_status"] == "RECALLED":
        raise ApiError("ERR_SAFETY_RECALL_HOLD", 409, "Appliance under active recall")

    routing = sr["warranty_routing"]
    contract = DB["warranty_contracts"].get(sr["covering_contract_id"]) if sr["covering_contract_id"] else None
    required_parts = approved_est["required_parts"] if approved_est else []

    # consume parts
    for line in required_parts:
        ts = find_truck_stock(sr["assigned_technician_id"], line["part_id"])
        if ts:
            ts["quantity_on_hand"] -= line["quantity"]
            ts["quantity_reserved"] -= line["quantity"]
            recompute_truck(ts)
            touch(ts)

    final_labor = labor_cost(b["actual_labor_tasks"])
    final_parts = parts_total(required_parts)
    final_subtotal = final_parts + final_labor
    diag_final = diagnostic_effective(routing, final_subtotal, completed=True)
    recall_applies = appliance["recall_status"] == "RECALLED"

    provisional_covered = sr["warranty_covered_cents"]
    if contract:
        base_claimed = contract["claimed_cents"] - provisional_covered
        cap_remaining = contract["coverage_cap_cents"] - base_claimed
    else:
        base_claimed = 0
        cap_remaining = 0

    if recall_applies:
        covered_final, cust_resp_final = 0, 0
    elif routing == "NONE":
        covered_final, cust_resp_final = 0, final_subtotal + diag_final
    elif routing == "MANUFACTURER":
        covered_final = min(final_subtotal, cap_remaining)
        cust_resp_final = final_subtotal - covered_final
    else:  # EXTENDED / HOME_WARRANTY
        covered_final = min(final_subtotal, cap_remaining)
        cust_resp_final = contract["deductible_cents"] + (final_subtotal - covered_final)

    if contract:
        contract["claimed_cents"] = base_claimed + covered_final
        recompute_contract(contract)
        touch(contract)

    sr["final_labor_total_cents"] = final_labor
    sr["final_parts_total_cents"] = final_parts
    sr["final_repair_subtotal_cents"] = final_subtotal
    sr["warranty_covered_cents"] = covered_final
    sr["customer_responsibility_cents"] = cust_resp_final
    sr["amount_due_cents"] = cust_resp_final

    # appliance completion
    appliance["completed_repair_count"] += 1
    appliance["_hs_service_date"] = parse_date(sr["_service_date"]) if sr.get("_service_date") else appliance["_hs_service_date"]
    appliance["_hs_prior_repairs"] = appliance["completed_repair_count"]
    recompute_appliance_health(appliance)
    touch(appliance)

    appt = current_booked_appointment(sid)
    if appt:
        appt["status"] = "COMPLETED"
        touch(appt)

    sr["status"] = "COMPLETED"
    touch(sr)
    cancel_open_parts_orders(sid)
    return ok(serialize(sr))


def cancel_open_parts_orders(sid):
    for po in DB["parts_orders"].values():
        if po["service_request_id"] == sid and po["status"] in ("ORDERED", "BACKORDERED"):
            po["status"] = "CANCELLED"
            touch(po)


@app.route("/service-requests/<sid>/second-trip", methods=["POST"])
def second_trip(sid):
    require_role("Technician")
    b = body()
    require(b, "part_id", "quantity")
    sr = get_or_404("service_requests", sid)
    as_int(b["quantity"], "quantity")
    # state (priority 4)
    if sr["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Second trip requires APPROVED request")
    # ownership (priority 6)
    if g.uid != sr["assigned_technician_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Only the assigned technician may order a second trip")
    get_or_404("parts", b["part_id"])

    po = new_entity(
        service_request_id=sid,
        part_id=b["part_id"],
        quantity=b["quantity"],
        status="ORDERED",
    )
    DB["parts_orders"][po["id"]] = po

    appt = current_booked_appointment(sid)
    if appt:
        appt["status"] = "CANCELLED"
        touch(appt)

    sr["status"] = "AWAITING_PARTS"
    touch(sr)
    return ok(serialize(sr))


@app.route("/service-requests/<sid>/payments", methods=["POST"])
def create_payment(sid):
    require_role("Customer", "ServiceAdmin")
    b = body()
    require(b, "amount_cents", "method")
    sr = get_or_404("service_requests", sid)
    as_int(b["amount_cents"], "amount_cents")
    if b["method"] not in ("CARD", "CHECK", "CASH"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid payment method")
    # ownership (priority 6)
    if g.role == "Customer" and g.uid != sr["customer_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Customer may only pay own request")
    # amount match (priority 14)
    if b["amount_cents"] != sr["amount_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422, "Payment amount mismatch")
    p = new_entity(
        service_request_id=sid,
        amount_cents=b["amount_cents"],
        method=b["method"],
        status="RECORDED",
    )
    DB["payments"][p["id"]] = p
    return ok(serialize(p), 201)


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------
@app.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    return ok(serialize(get_or_404("estimates", eid)))


@app.route("/estimates", methods=["GET"])
def list_estimates():
    return paginate(
        list(DB["estimates"].values()),
        {"service_request_id": request.args.get("service_request_id")},
    )


@app.route("/estimates/<eid>/decision", methods=["POST"])
def estimate_decision(eid):
    require_role("Customer")
    b = body()
    require(b, "decision")
    est = get_or_404("estimates", eid)
    decision = b["decision"]
    if isinstance(decision, str):
        decision = decision.upper()
    if decision not in ("APPROVE", "DECLINE"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid decision")
    sr = get_or_404("service_requests", est["service_request_id"])
    # estimate pending (priority 5)
    if est["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_ESTIMATE_NOT_PENDING", 409, "Estimate is not pending approval")
    # ownership (priority 6)
    if g.uid != sr["customer_id"]:
        raise ApiError("ERR_NOT_OWNER", 403, "Only the owning customer may decide")

    if decision == "DECLINE":
        est["status"] = "DECLINED"
        touch(est)
        sr["status"] = "DECLINED"
        sr["amount_due_cents"] = sr["diagnostic_fee_cents"]
        touch(sr)
        cancel_open_parts_orders(sr["id"])
        return ok(serialize(est))

    # APPROVE
    appliance = get_or_404("appliances", sr["appliance_id"])
    # safety (priority 7)
    if appliance["recall_status"] == "RECALLED":
        raise ApiError("ERR_SAFETY_RECALL_HOLD", 409, "Appliance under active recall")
    # sufficient truck stock (priority 13) — aggregate per part, atomic
    needed = {}
    for line in est["required_parts"]:
        needed[line["part_id"]] = needed.get(line["part_id"], 0) + line["quantity"]
    for part_id, qty in needed.items():
        ts = find_truck_stock(sr["assigned_technician_id"], part_id)
        available = ts["quantity_available"] if ts else 0
        if available < qty:
            raise ApiError("ERR_INSUFFICIENT_TRUCK_STOCK", 409, "Insufficient truck stock")

    routing = sr["warranty_routing"]
    contract = DB["warranty_contracts"].get(sr["covering_contract_id"]) if sr["covering_contract_id"] else None
    subtotal = est["estimated_repair_subtotal_cents"]
    diag = est["estimated_diagnostic_fee_cents"]
    recall_applies = appliance["recall_status"] == "RECALLED"
    covered, cust_resp = warranty_split(subtotal, contract, routing, recall_applies, diag)

    # reserve
    for part_id, qty in needed.items():
        ts = find_truck_stock(sr["assigned_technician_id"], part_id)
        ts["quantity_reserved"] += qty
        recompute_truck(ts)
        touch(ts)
    # commit warranty claim
    if contract:
        contract["claimed_cents"] += covered
        recompute_contract(contract)
        touch(contract)

    sr["warranty_covered_cents"] = covered
    sr["customer_responsibility_cents"] = cust_resp

    est["status"] = "APPROVED"
    touch(est)
    sr["status"] = "APPROVED"
    touch(sr)
    return ok(serialize(est))


# ---------------------------------------------------------------------------
# PartsOrder
# ---------------------------------------------------------------------------
@app.route("/parts-orders/<pid>", methods=["GET"])
def get_parts_order(pid):
    return ok(serialize(get_or_404("parts_orders", pid)))


@app.route("/parts-orders", methods=["GET"])
def list_parts_orders():
    return paginate(
        list(DB["parts_orders"].values()),
        {
            "service_request_id": request.args.get("service_request_id"),
            "part_id": request.args.get("part_id"),
        },
    )


@app.route("/parts-orders/<pid>/status", methods=["POST"])
def parts_order_status(pid):
    require_role("Technician", "Dispatcher", "ServiceAdmin")
    b = body()
    require(b, "to_status")
    po = get_or_404("parts_orders", pid)
    to_status = b["to_status"]
    if to_status not in ("ORDERED", "BACKORDERED", "RECEIVED"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_status")
    allowed = {
        ("ORDERED", "RECEIVED"),
        ("ORDERED", "BACKORDERED"),
        ("BACKORDERED", "ORDERED"),
    }
    if (po["status"], to_status) not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid parts order transition")
    po["status"] = to_status
    touch(po)
    return ok(serialize(po))


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    return ok(serialize(get_or_404("payments", pid)))


@app.route("/payments", methods=["GET"])
def list_payments():
    return paginate(
        list(DB["payments"].values()),
        {"service_request_id": request.args.get("service_request_id")},
    )


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------
@app.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    return ok(serialize(get_or_404("appointments", aid)))


@app.route("/appointments", methods=["GET"])
def list_appointments():
    return paginate(
        list(DB["appointments"].values()),
        {
            "service_request_id": request.args.get("service_request_id"),
            "technician_id": request.args.get("technician_id"),
            "zone_id": request.args.get("zone_id"),
        },
    )


# ---------------------------------------------------------------------------
# RecallNotice
# ---------------------------------------------------------------------------
@app.route("/recalls", methods=["POST"])
def create_recall():
    require_role("ServiceAdmin")
    b = body()
    require(b, "brand", "model", "description")
    r = new_entity(
        brand=b["brand"], model=b["model"], description=b["description"], status="ISSUED"
    )
    DB["recalls"][r["id"]] = r
    return ok(serialize(r), 201)


@app.route("/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    return ok(serialize(get_or_404("recalls", rid)))


@app.route("/recalls/<rid>/status", methods=["POST"])
def recall_status(rid):
    require_role("ServiceAdmin")
    b = body()
    require(b, "to_status")
    r = get_or_404("recalls", rid)
    to_status = b["to_status"]
    if to_status not in ("ACTIVE", "RESCINDED"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_status")
    if not ((r["status"] == "ISSUED" and to_status == "ACTIVE") or
            (r["status"] == "ACTIVE" and to_status == "RESCINDED")):
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid recall transition")

    if to_status == "ACTIVE":
        r["status"] = "ACTIVE"
        touch(r)
        activate_recall_cascade(r)
    else:
        r["status"] = "RESCINDED"
        touch(r)
        rescind_recall_cascade(r)
    return ok(serialize(r))


def activate_recall_cascade(recall):
    for appliance in list(DB["appliances"].values()):
        if appliance["brand"] != recall["brand"] or appliance["model"] != recall["model"]:
            continue
        if appliance["recall_status"] != "RECALLED":
            appliance["recall_status"] = "RECALLED"
            recompute_appliance_health(appliance)
            touch(appliance)
        # non-terminal requests on this appliance -> SAFETY_HOLD
        for sr in list(DB["service_requests"].values()):
            if sr["appliance_id"] != appliance["id"]:
                continue
            if sr["status"] in SR_TERMINAL:
                continue
            safety_hold_request(sr)


def safety_hold_request(sr):
    approved_est = find_approved_estimate(sr["id"])
    if approved_est is not None:
        # reverse reservations
        for line in approved_est["required_parts"]:
            ts = find_truck_stock(sr["assigned_technician_id"], line["part_id"])
            if ts:
                ts["quantity_reserved"] -= line["quantity"]
                recompute_truck(ts)
                touch(ts)
        # reverse warranty claim
        if sr["covering_contract_id"]:
            contract = DB["warranty_contracts"].get(sr["covering_contract_id"])
            if contract:
                contract["claimed_cents"] -= sr["warranty_covered_cents"]
                recompute_contract(contract)
                touch(contract)
    sr["status"] = "SAFETY_HOLD"
    touch(sr)
    appt = current_booked_appointment(sr["id"])
    if appt:
        appt["status"] = "CANCELLED"
        touch(appt)
    cancel_open_parts_orders(sr["id"])


def rescind_recall_cascade(recall):
    for appliance in list(DB["appliances"].values()):
        if appliance["brand"] != recall["brand"] or appliance["model"] != recall["model"]:
            continue
        if matching_active_recall(appliance["brand"], appliance["model"]):
            continue
        if appliance["recall_status"] == "RECALLED":
            appliance["recall_status"] = "CLEAR"
            recompute_appliance_health(appliance)
            touch(appliance)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
