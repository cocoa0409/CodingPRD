import os
import re
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Customer", "Technician", "ServiceAdvisor", "StoreManager"}

LABOR_RATE_STANDARD = 5000
LABOR_RATE_MASTER = 8000
DIAGNOSTIC_FEE_CENTS = 4000
REPLACE_THRESHOLD_PCT = "0.60"
GRADE_MULTIPLIER = {"A": "0.90", "B": "0.70", "C": "0.45", "D": "0.20"}
ACCESSORY_BONUS_PCT = "0.05"
COSMETIC_DEDUCT_PCT = "0.03"
DEDUCTIBLE_BY_PLAN = {"ADH": 7500, "EXTENDED_WARRANTY": 0, "ACCESSORY": 2500}
COVERAGE_CAP_CENTS = 50000
WARRANTY_DAYS = 90
CLEANING_BUFFER_MINUTES = 30

DEVICE_CATEGORIES = {"PHONE", "LAPTOP", "TABLET", "WEARABLE"}
INTAKE_CHANNELS = {"WALK_IN", "MAIL_IN"}
CERT_LEVELS = {"STANDARD", "MASTER"}
GRADES = {"A", "B", "C", "D"}
WIPE_METHODS = {"CRYPTO_ERASE", "FACTORY_RESET", "PHYSICAL_DESTRUCTION"}
WIPE_RESULTS = {"SUCCESS", "FAILED"}
PLAN_TYPES = {"ADH", "EXTENDED_WARRANTY", "ACCESSORY"}
ROUTING_BY_PLAN = {"ADH": "IN_STORE", "EXTENDED_WARRANTY": "MANUFACTURER", "ACCESSORY": "THIRD_PARTY_ADMIN"}

TICKET_NONTERMINAL = {"INTAKE", "DIAGNOSING", "AWAITING_APPROVAL", "IN_REPAIR"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.customers = {}
        self.technicians = {}
        self.bays = {}
        self.devices = {}
        self.tickets = {}
        self.estimates = {}
        self.parts = {}
        self.part_orders = {}
        self.trade_ins = {}
        self.certificates = {}
        self.claims = {}
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = itertools.count(1)

db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_wall():
    return datetime.now(timezone.utc)


def format_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return format_dt(now_wall())


def parse_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def rhu_mul(base, factor):
    return int((Decimal(str(base)) * Decimal(str(factor))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def base_record(common=True):
    ts = now_ts()
    rec = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next(db.seq)}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": req_id(), "api_request_timestamp": now_ts()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = base_meta()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def obj(rec, status=200):
    return ok(serialize(rec), status=status, response_type="object")


def arr(records, pagination):
    return ok([serialize(r) for r in records], status=200, response_type="array", pagination=pagination)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", 400, "missing or invalid user context")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(*allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted")


def own_or_403(customer_id):
    if g.user_id != customer_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the owner")


# ---------------------------------------------------------------------------
# Body helpers / validation
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "invalid body")
    return body


def v_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
    return v


def v_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"{field} is invalid")
    return v


def v_int(body, field, minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 422, f"{field} out of range")
    return v


def v_int_default(body, field, default, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return v_int(body, field, minimum=minimum)


def v_bool_default(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a boolean")
    return v


def v_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a number")
    return v


def v_quantity(body, field="quantity"):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an integer")
    if v < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 422, f"{field} must be >= 1")
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, key, error_id):
    rec = coll.get(key)
    if rec is None:
        raise ApiError(error_id, 404, "not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(records):
    records = sorted(records, key=lambda r: r["_seq"])
    total = len(records)
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    page = records[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def labor_rate(tech):
    return LABOR_RATE_MASTER if tech["certification_level"] == "MASTER" else LABOR_RATE_STANDARD


def estimate_total(tech, labor_hours, part_orders, is_under_warranty):
    labor_cost = rhu_mul(labor_rate(tech), labor_hours)
    parts_cost = sum(po["line_cost_cents"] for po in part_orders)
    diagnostic = 0 if is_under_warranty else DIAGNOSTIC_FEE_CENTS
    total = labor_cost + parts_cost + diagnostic
    return labor_cost, parts_cost, diagnostic, total


def recommendation_for(provisional_total, device):
    threshold = rhu_mul(device["market_value_cents"], REPLACE_THRESHOLD_PCT)
    return "REPLACE" if provisional_total >= threshold else "REPAIR"


def trade_in_payout(device, grade, has_accessories, defect_count):
    base = device["market_value_cents"]
    graded = rhu_mul(base, GRADE_MULTIPLIER[grade])
    accessory = rhu_mul(base, ACCESSORY_BONUS_PCT) if has_accessories else 0
    cosmetic_each = rhu_mul(base, COSMETIC_DEDUCT_PCT)
    payout = graded + accessory - (cosmetic_each * defect_count)
    return max(payout, 0)


def recompute_part(part):
    part["available_qty"] = part["on_hand_qty"] - part["reserved_qty"]


def ticket_part_orders(ticket_id):
    return [po for po in db.part_orders.values() if po["repair_ticket_id"] == ticket_id]


def ticket_estimates(ticket_id):
    return [e for e in db.estimates.values() if e["repair_ticket_id"] == ticket_id]


def approved_estimate(ticket_id):
    for e in ticket_estimates(ticket_id):
        if e["status"] in ("APPROVED", "FINALIZED"):
            return e
    return None


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth()
    require_role("Customer", "Technician", "ServiceAdvisor", "StoreManager")
    body = get_body()
    target = body.get("to_iso8601")
    db.clock = parse_dt(target)
    return ok({}, status=200, response_type="object")


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    require_auth()
    require_role("ServiceAdvisor")
    body = get_body()
    rec = base_record()
    rec.update({
        "full_name": v_str(body, "full_name"),
        "email": v_str(body, "email"),
        "phone": v_str(body, "phone"),
        "store_credit_balance_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND"))


# ===========================================================================
# Technician
# ===========================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    require_auth()
    require_role("StoreManager")
    body = get_body()
    rec = base_record()
    rec.update({
        "full_name": v_str(body, "full_name"),
        "certification_level": v_enum(body, "certification_level", CERT_LEVELS),
    })
    db.technicians[rec["id"]] = rec
    return obj(rec, status=201)


# ===========================================================================
# RepairBay
# ===========================================================================
@app.route("/repair-bays", methods=["POST"])
def create_bay():
    require_auth()
    require_role("StoreManager")
    body = get_body()
    rec = base_record()
    rec.update({"bay_name": v_str(body, "bay_name")})
    db.bays[rec["id"]] = rec
    return obj(rec, status=201)


# ===========================================================================
# Device
# ===========================================================================
@app.route("/devices", methods=["POST"])
def create_device():
    require_auth()
    require_role("ServiceAdvisor")
    body = get_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or customer_id == "":
        raise ApiError("ERR_VALIDATION", 422, "customer_id is required")
    get_or_404(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    rec = base_record()
    rec.update({
        "customer_id": customer_id,
        "category": v_enum(body, "category", DEVICE_CATEGORIES),
        "brand": v_str(body, "brand"),
        "model": v_str(body, "model"),
        "serial_number": v_str(body, "serial_number"),
        "market_value_cents": v_int(body, "market_value_cents", minimum=0),
    })
    db.devices[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/devices/<device_id>", methods=["GET"])
def get_device(device_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.devices, device_id, "ERR_DEVICE_NOT_FOUND"))


@app.route("/devices", methods=["GET"])
def list_devices():
    require_auth()
    require_role(*ROLES)
    records = list(db.devices.values())
    cust = request.args.get("customer_id")
    if cust is not None:
        records = [r for r in records if r["customer_id"] == cust]
    page, pg = paginate(records)
    return arr(page, pg)


# ===========================================================================
# RepairTicket
# ===========================================================================
@app.route("/repair-tickets", methods=["POST"])
def create_ticket():
    require_auth()
    require_role("ServiceAdvisor")
    body = get_body()
    device_id = body.get("device_id")
    customer_id = body.get("customer_id")
    if not isinstance(device_id, str) or device_id == "":
        raise ApiError("ERR_VALIDATION", 422, "device_id is required")
    if not isinstance(customer_id, str) or customer_id == "":
        raise ApiError("ERR_VALIDATION", 422, "customer_id is required")
    get_or_404(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    get_or_404(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    intake_channel = v_enum(body, "intake_channel", INTAKE_CHANNELS)
    reported_issue = v_str(body, "reported_issue")
    is_under_warranty = v_bool_default(body, "is_under_warranty", False)
    spend_cap = v_int(body, "spend_cap_cents", minimum=0)
    rec = base_record()
    rec.update({
        "device_id": device_id,
        "customer_id": customer_id,
        "original_ticket_id": None,
        "intake_channel": intake_channel,
        "reported_issue": reported_issue,
        "is_under_warranty": is_under_warranty,
        "is_callback": False,
        "spend_cap_cents": spend_cap,
        "assigned_technician_id": None,
        "assigned_bay_id": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "completed_at": None,
        "final_invoice_cents": None,
        "status": "INTAKE",
    })
    db.tickets[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/repair-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND"))


@app.route("/repair-tickets", methods=["GET"])
def list_tickets():
    require_auth()
    require_role(*ROLES)
    records = list(db.tickets.values())
    for field in ("device_id", "customer_id", "assigned_technician_id",
                  "assigned_bay_id", "original_ticket_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    page, pg = paginate(records)
    return arr(page, pg)


@app.route("/repair-tickets/<ticket_id>/diagnose", methods=["POST"])
def diagnose(ticket_id):
    require_auth()
    require_role("Technician")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    body = get_body()
    tech_id = body.get("assigned_technician_id")
    bay_id = body.get("assigned_bay_id")
    if not isinstance(tech_id, str) or tech_id == "":
        raise ApiError("ERR_VALIDATION", 422, "assigned_technician_id is required")
    if not isinstance(bay_id, str) or bay_id == "":
        raise ApiError("ERR_VALIDATION", 422, "assigned_bay_id is required")
    get_or_404(db.technicians, tech_id, "ERR_TECHNICIAN_NOT_FOUND")
    get_or_404(db.bays, bay_id, "ERR_BAY_NOT_FOUND")
    start_s = v_str(body, "scheduled_start_at")
    end_s = v_str(body, "scheduled_end_at")
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL", 422, "end must be after start")
    if ticket["status"] != "INTAKE":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "ticket not in INTAKE")

    # technician double-booking: half-open [start, end)
    for other in db.tickets.values():
        if other["id"] == ticket_id:
            continue
        if other["status"] not in TICKET_NONTERMINAL:
            continue
        if other.get("assigned_technician_id") != tech_id:
            continue
        if not other.get("scheduled_start_at"):
            continue
        os_ = parse_dt(other["scheduled_start_at"])
        oe_ = parse_dt(other["scheduled_end_at"])
        if start < oe_ and os_ < end:
            raise ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED", 409, "technician double-booked")

    # bay: closed [start, end] plus cleaning buffer
    buffer = timedelta(minutes=CLEANING_BUFFER_MINUTES)
    for other in db.tickets.values():
        if other["id"] == ticket_id:
            continue
        if other["status"] not in TICKET_NONTERMINAL:
            continue
        if other.get("assigned_bay_id") != bay_id:
            continue
        if not other.get("scheduled_start_at"):
            continue
        os_ = parse_dt(other["scheduled_start_at"])
        oe_ = parse_dt(other["scheduled_end_at"])
        if start > oe_:
            sep = start - oe_
        elif os_ > end:
            sep = os_ - end
        else:
            sep = timedelta(0)
        if sep < buffer:
            raise ApiError("ERR_BAY_UNAVAILABLE", 409, "bay unavailable within cleaning buffer")

    ticket["assigned_technician_id"] = tech_id
    ticket["assigned_bay_id"] = bay_id
    ticket["scheduled_start_at"] = start_s
    ticket["scheduled_end_at"] = end_s
    ticket["status"] = "DIAGNOSING"
    touch(ticket)
    return obj(ticket, status=200)


@app.route("/repair-tickets/<ticket_id>/estimates", methods=["POST"])
def create_estimate(ticket_id):
    require_auth()
    require_role("Technician")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    body = get_body()
    labor_hours = v_number(body, "labor_hours")
    expected = v_int(body, "expected_repair_ticket_version")
    if ticket["status"] != "DIAGNOSING":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "ticket not in DIAGNOSING")
    if expected != ticket["version"]:
        raise ApiError("ERR_STALE_TICKET_VERSION", 412, "stale ticket version")

    tech = db.technicians.get(ticket.get("assigned_technician_id"))
    if tech is None:
        raise ApiError("ERR_TECHNICIAN_NOT_FOUND", 404, "assigned technician missing")
    device = db.devices[ticket["device_id"]]

    active_pos = [po for po in ticket_part_orders(ticket_id)
                  if po["status"] in ("REQUESTED", "RESERVED", "BACKORDERED")]
    labor_cost, parts_cost, diagnostic, total = estimate_total(
        tech, labor_hours, active_pos, ticket["is_under_warranty"])

    # supersede prior live estimates
    prior = [e for e in ticket_estimates(ticket_id) if e["status"] in ("SENT", "REJECTED")]
    rev = len(ticket_estimates(ticket_id)) + 1
    for e in prior:
        e["status"] = "SUPERSEDED"
        touch(e)

    rec = base_record()
    rec.update({
        "repair_ticket_id": ticket_id,
        "revision_number": rev,
        "labor_hours": labor_hours,
        "labor_cost_cents": labor_cost,
        "parts_cost_cents": parts_cost,
        "diagnostic_fee_cents": diagnostic,
        "provisional_total_cents": total,
        "final_total_cents": None,
        "recommendation": recommendation_for(total, device),
        "status": "SENT",
    })
    db.estimates[rec["id"]] = rec

    ticket["status"] = "AWAITING_APPROVAL"
    touch(ticket)
    return obj(rec, status=201)


def _resolve_estimate(ticket_id, estimate_id):
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    estimate = db.estimates.get(estimate_id)
    if estimate is None or estimate["repair_ticket_id"] != ticket_id:
        raise ApiError("ERR_ESTIMATE_NOT_FOUND", 404, "estimate not found")
    return ticket, estimate


@app.route("/repair-tickets/<ticket_id>/estimates", methods=["GET"])
def list_estimates(ticket_id):
    require_auth()
    require_role(*ROLES)
    get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    records = ticket_estimates(ticket_id)
    page, pg = paginate(records)
    return arr(page, pg)


@app.route("/repair-tickets/<ticket_id>/estimates/<estimate_id>", methods=["GET"])
def get_estimate(ticket_id, estimate_id):
    require_auth()
    require_role(*ROLES)
    _, estimate = _resolve_estimate(ticket_id, estimate_id)
    return obj(estimate)


@app.route("/repair-tickets/<ticket_id>/estimates/<estimate_id>/approve", methods=["POST"])
def approve_estimate(ticket_id, estimate_id):
    require_auth()
    require_role("Customer")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    own_or_403(ticket["customer_id"])
    estimate = db.estimates.get(estimate_id)
    if estimate is None or estimate["repair_ticket_id"] != ticket_id:
        raise ApiError("ERR_ESTIMATE_NOT_FOUND", 404, "estimate not found")
    if estimate["status"] != "SENT":
        raise ApiError("ERR_ESTIMATE_NOT_SENT", 409, "estimate not SENT")
    if ticket["status"] != "AWAITING_APPROVAL":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "ticket not AWAITING_APPROVAL")
    if estimate["provisional_total_cents"] > ticket["spend_cap_cents"]:
        raise ApiError("ERR_SPEND_CAP_EXCEEDED", 402, "estimate exceeds spend cap")
    estimate["status"] = "APPROVED"
    touch(estimate)
    ticket["status"] = "IN_REPAIR"
    touch(ticket)
    return obj(estimate, status=200)


@app.route("/repair-tickets/<ticket_id>/estimates/<estimate_id>/reject", methods=["POST"])
def reject_estimate(ticket_id, estimate_id):
    require_auth()
    require_role("Customer")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    own_or_403(ticket["customer_id"])
    estimate = db.estimates.get(estimate_id)
    if estimate is None or estimate["repair_ticket_id"] != ticket_id:
        raise ApiError("ERR_ESTIMATE_NOT_FOUND", 404, "estimate not found")
    if estimate["status"] != "SENT":
        raise ApiError("ERR_ESTIMATE_NOT_SENT", 409, "estimate not SENT")
    if ticket["status"] != "AWAITING_APPROVAL":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "ticket not AWAITING_APPROVAL")
    estimate["status"] = "REJECTED"
    touch(estimate)
    ticket["status"] = "DIAGNOSING"
    touch(ticket)
    return obj(estimate, status=200)


@app.route("/repair-tickets/<ticket_id>/complete", methods=["POST"])
def complete_ticket(ticket_id):
    require_auth()
    require_role("Technician")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    body = get_body()
    actual_labor_hours = v_number(body, "actual_labor_hours")
    if ticket["status"] != "IN_REPAIR":
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "ticket not IN_REPAIR")
    estimate = None
    for e in ticket_estimates(ticket_id):
        if e["status"] == "APPROVED":
            estimate = e
            break
    if estimate is None:
        raise ApiError("ERR_ESTIMATE_NOT_APPROVED", 409, "no approved estimate")

    tech = db.technicians.get(ticket.get("assigned_technician_id"))

    # install reserved part orders (driven by finalization)
    for po in ticket_part_orders(ticket_id):
        if po["status"] == "RESERVED":
            po["status"] = "INSTALLED"
            touch(po)
            part = db.parts[po["part_id"]]
            part["on_hand_qty"] -= po["quantity"]
            part["reserved_qty"] -= po["quantity"]
            recompute_part(part)
            touch(part)

    installed = [po for po in ticket_part_orders(ticket_id) if po["status"] == "INSTALLED"]
    labor_cost, parts_cost, diagnostic, final_total = estimate_total(
        tech, actual_labor_hours, installed, ticket["is_under_warranty"])

    estimate["final_total_cents"] = final_total
    estimate["status"] = "FINALIZED"
    touch(estimate)

    ticket["completed_at"] = format_dt(db.clock)
    ticket["final_invoice_cents"] = final_total
    ticket["status"] = "COMPLETED"
    touch(ticket)
    return obj(ticket, status=200)


@app.route("/repair-tickets/<ticket_id>/cancel", methods=["POST"])
def cancel_ticket(ticket_id):
    require_auth()
    require_role("ServiceAdvisor")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    if ticket["status"] not in ("INTAKE", "DIAGNOSING", "AWAITING_APPROVAL"):
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "ticket cannot be cancelled")
    for po in ticket_part_orders(ticket_id):
        if po["status"] == "RESERVED":
            po["status"] = "RETURNED"
            touch(po)
            part = db.parts[po["part_id"]]
            part["reserved_qty"] -= po["quantity"]
            recompute_part(part)
            touch(part)
    for e in ticket_estimates(ticket_id):
        if e["status"] == "SENT":
            e["status"] = "SUPERSEDED"
            touch(e)
    ticket["status"] = "CANCELLED"
    touch(ticket)
    return obj(ticket, status=200)


@app.route("/repair-tickets/<ticket_id>/callback", methods=["POST"])
def callback_ticket(ticket_id):
    require_auth()
    require_role("ServiceAdvisor")
    original = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    body = get_body()
    reported_issue = v_str(body, "reported_issue")
    intake_channel = v_enum(body, "intake_channel", INTAKE_CHANNELS)
    if original["status"] != "COMPLETED" or not original.get("completed_at"):
        raise ApiError("ERR_TICKET_INVALID_STATE", 409, "original ticket not completed")
    completed = parse_dt(original["completed_at"])
    expiry = completed + timedelta(days=WARRANTY_DAYS)
    if db.clock > expiry:
        raise ApiError("ERR_WARRANTY_EXPIRED", 422, "warranty window closed")
    rec = base_record()
    rec.update({
        "device_id": original["device_id"],
        "customer_id": original["customer_id"],
        "original_ticket_id": ticket_id,
        "intake_channel": intake_channel,
        "reported_issue": reported_issue,
        "is_under_warranty": True,
        "is_callback": True,
        "spend_cap_cents": original["spend_cap_cents"],
        "assigned_technician_id": None,
        "assigned_bay_id": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "completed_at": None,
        "final_invoice_cents": None,
        "status": "INTAKE",
    })
    db.tickets[rec["id"]] = rec
    return obj(rec, status=201)


# ===========================================================================
# Part
# ===========================================================================
@app.route("/parts", methods=["POST"])
def create_part():
    require_auth()
    require_role("StoreManager")
    body = get_body()
    rec = base_record()
    on_hand = v_int_default(body, "on_hand_qty", 0, minimum=0)
    rec.update({
        "sku": v_str(body, "sku"),
        "name": v_str(body, "name"),
        "unit_price_cents": v_int(body, "unit_price_cents", minimum=0),
        "on_hand_qty": on_hand,
        "reserved_qty": 0,
        "available_qty": on_hand,
    })
    db.parts[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/parts/<part_id>", methods=["GET"])
def get_part(part_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.parts, part_id, "ERR_PART_NOT_FOUND"))


@app.route("/parts/<part_id>/receive-stock", methods=["POST"])
def receive_stock(part_id):
    require_auth()
    require_role("StoreManager")
    part = get_or_404(db.parts, part_id, "ERR_PART_NOT_FOUND")
    body = get_body()
    qty = v_quantity(body, "quantity")
    part["on_hand_qty"] += qty
    recompute_part(part)
    touch(part)
    return obj(part, status=200)


# ===========================================================================
# PartOrder
# ===========================================================================
@app.route("/repair-tickets/<ticket_id>/part-orders", methods=["POST"])
def create_part_order(ticket_id):
    require_auth()
    require_role("Technician")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    body = get_body()
    part_id = body.get("part_id")
    if not isinstance(part_id, str) or part_id == "":
        raise ApiError("ERR_VALIDATION", 422, "part_id is required")
    part = get_or_404(db.parts, part_id, "ERR_PART_NOT_FOUND")
    qty = v_quantity(body, "quantity")
    line_cost = part["unit_price_cents"] * qty
    rec = base_record()
    if part["available_qty"] >= qty:
        status = "RESERVED"
        part["reserved_qty"] += qty
        recompute_part(part)
        touch(part)
    else:
        status = "BACKORDERED"
    rec.update({
        "repair_ticket_id": ticket_id,
        "part_id": part_id,
        "quantity": qty,
        "line_cost_cents": line_cost,
        "status": status,
    })
    db.part_orders[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/part-orders/<part_order_id>", methods=["GET"])
def get_part_order(part_order_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.part_orders, part_order_id, "ERR_PART_ORDER_NOT_FOUND"))


@app.route("/part-orders", methods=["GET"])
def list_part_orders():
    require_auth()
    require_role(*ROLES)
    records = list(db.part_orders.values())
    for field in ("repair_ticket_id", "part_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    page, pg = paginate(records)
    return arr(page, pg)


@app.route("/part-orders/<part_order_id>/restock", methods=["POST"])
def restock_part_order(part_order_id):
    require_auth()
    require_role("StoreManager")
    po = get_or_404(db.part_orders, part_order_id, "ERR_PART_ORDER_NOT_FOUND")
    if po["status"] != "BACKORDERED":
        raise ApiError("ERR_PART_ORDER_INVALID_STATE", 409, "part order not BACKORDERED")
    part = db.parts[po["part_id"]]
    if part["available_qty"] < po["quantity"]:
        raise ApiError("ERR_PART_OUT_OF_STOCK", 409, "part out of stock")
    part["reserved_qty"] += po["quantity"]
    recompute_part(part)
    touch(part)
    po["status"] = "RESERVED"
    touch(po)
    return obj(po, status=200)


# ===========================================================================
# TradeIn
# ===========================================================================
@app.route("/trade-ins", methods=["POST"])
def create_trade_in():
    require_auth()
    require_role("ServiceAdvisor")
    body = get_body()
    customer_id = body.get("customer_id")
    device_id = body.get("device_id")
    if not isinstance(customer_id, str) or customer_id == "":
        raise ApiError("ERR_VALIDATION", 422, "customer_id is required")
    if not isinstance(device_id, str) or device_id == "":
        raise ApiError("ERR_VALIDATION", 422, "device_id is required")
    get_or_404(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    device = get_or_404(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    declared_grade = v_enum(body, "declared_grade", GRADES)
    quoted = trade_in_payout(device, declared_grade, False, 0)
    rec = base_record()
    rec.update({
        "customer_id": customer_id,
        "device_id": device_id,
        "declared_grade": declared_grade,
        "assessed_grade": None,
        "has_accessories": False,
        "assessed_cosmetic_defect_count": 0,
        "quoted_payout_cents": quoted,
        "final_payout_cents": None,
        "status": "SUBMITTED",
    })
    db.trade_ins[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/trade-ins/<trade_in_id>", methods=["GET"])
def get_trade_in(trade_in_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND"))


@app.route("/trade-ins", methods=["GET"])
def list_trade_ins():
    require_auth()
    require_role(*ROLES)
    records = list(db.trade_ins.values())
    for field in ("customer_id", "device_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    page, pg = paginate(records)
    return arr(page, pg)


@app.route("/trade-ins/<trade_in_id>/offer", methods=["POST"])
def offer_trade_in(trade_in_id):
    require_auth()
    require_role("Technician")
    ti = get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    body = get_body()
    assessed_grade = v_enum(body, "assessed_grade", GRADES)
    has_accessories = v_bool_default(body, "has_accessories", False)
    defect_count = v_int_default(body, "assessed_cosmetic_defect_count", 0, minimum=0)
    if ti["status"] != "SUBMITTED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE", 409, "trade-in not SUBMITTED")
    device = db.devices[ti["device_id"]]
    final_payout = trade_in_payout(device, assessed_grade, has_accessories, defect_count)
    ti["assessed_grade"] = assessed_grade
    ti["has_accessories"] = has_accessories
    ti["assessed_cosmetic_defect_count"] = defect_count
    ti["final_payout_cents"] = final_payout
    ti["status"] = "OFFER_MADE"
    touch(ti)
    return obj(ti, status=200)


@app.route("/trade-ins/<trade_in_id>/dispute", methods=["POST"])
def dispute_trade_in(trade_in_id):
    require_auth()
    require_role("Customer")
    ti = get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    own_or_403(ti["customer_id"])
    if ti["status"] != "OFFER_MADE":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE", 409, "trade-in not OFFER_MADE")
    ti["assessed_grade"] = None
    ti["final_payout_cents"] = None
    ti["status"] = "SUBMITTED"
    touch(ti)
    return obj(ti, status=200)


@app.route("/trade-ins/<trade_in_id>/accept", methods=["POST"])
def accept_trade_in(trade_in_id):
    require_auth()
    require_role("Customer")
    ti = get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    own_or_403(ti["customer_id"])
    if ti["status"] != "OFFER_MADE":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE", 409, "trade-in not OFFER_MADE")
    ti["status"] = "ACCEPTED"
    touch(ti)
    customer = db.customers[ti["customer_id"]]
    customer["store_credit_balance_cents"] += ti["final_payout_cents"]
    touch(customer)
    return obj(ti, status=200)


@app.route("/trade-ins/<trade_in_id>/decline", methods=["POST"])
def decline_trade_in(trade_in_id):
    require_auth()
    require_role("Customer")
    ti = get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    own_or_403(ti["customer_id"])
    if ti["status"] != "OFFER_MADE":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE", 409, "trade-in not OFFER_MADE")
    ti["status"] = "DECLINED"
    touch(ti)
    return obj(ti, status=200)


@app.route("/trade-ins/<trade_in_id>/pay", methods=["POST"])
def pay_trade_in(trade_in_id):
    require_auth()
    require_role("StoreManager")
    ti = get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    if ti["status"] != "ACCEPTED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE", 409, "trade-in not ACCEPTED")
    device_id = ti["device_id"]
    for t in db.tickets.values():
        if t["device_id"] == device_id and t["status"] in TICKET_NONTERMINAL:
            raise ApiError("ERR_DEVICE_HAS_ACTIVE_TICKET", 409, "device has active ticket")
    has_wipe = any(c["device_id"] == device_id and c["wipe_result"] == "SUCCESS"
                   for c in db.certificates.values())
    if not has_wipe:
        raise ApiError("ERR_DATA_WIPE_REQUIRED", 422, "successful data-wipe certificate required")
    ti["status"] = "PAID"
    touch(ti)
    return obj(ti, status=200)


@app.route("/trade-ins/<trade_in_id>/cancel", methods=["POST"])
def cancel_trade_in(trade_in_id):
    require_auth()
    require_role("ServiceAdvisor")
    ti = get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    if ti["status"] != "ACCEPTED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE", 409, "trade-in not ACCEPTED")
    ti["status"] = "CANCELLED"
    touch(ti)
    customer = db.customers[ti["customer_id"]]
    customer["store_credit_balance_cents"] -= ti["final_payout_cents"]
    touch(customer)
    return obj(ti, status=200)


# ===========================================================================
# DataWipeCertificate
# ===========================================================================
@app.route("/data-wipe-certificates", methods=["POST"])
def create_certificate():
    require_auth()
    require_role("Technician")
    body = get_body()
    device_id = body.get("device_id")
    if not isinstance(device_id, str) or device_id == "":
        raise ApiError("ERR_VALIDATION", 422, "device_id is required")
    get_or_404(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    trade_in_id = body.get("trade_in_id")
    if trade_in_id is not None:
        if not isinstance(trade_in_id, str) or trade_in_id == "":
            raise ApiError("ERR_VALIDATION", 422, "trade_in_id is invalid")
        get_or_404(db.trade_ins, trade_in_id, "ERR_TRADE_IN_NOT_FOUND")
    method = v_enum(body, "method", WIPE_METHODS)
    wipe_result = v_enum(body, "wipe_result", WIPE_RESULTS)
    rec = base_record(common=False)
    rec.update({
        "device_id": device_id,
        "trade_in_id": trade_in_id,
        "method": method,
        "wipe_result": wipe_result,
        "certificate_number": "CERT-" + uuid.uuid4().hex[:12].upper(),
    })
    db.certificates[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/data-wipe-certificates/<certificate_id>", methods=["GET"])
def get_certificate(certificate_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND"))


@app.route("/data-wipe-certificates", methods=["GET"])
def list_certificates():
    require_auth()
    require_role(*ROLES)
    records = list(db.certificates.values())
    for field in ("device_id", "trade_in_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    page, pg = paginate(records)
    return arr(page, pg)


# ===========================================================================
# ProtectionPlanClaim
# ===========================================================================
@app.route("/protection-plan-claims", methods=["POST"])
def create_claim():
    require_auth()
    require_role("ServiceAdvisor")
    body = get_body()
    ticket_id = body.get("repair_ticket_id")
    customer_id = body.get("customer_id")
    if not isinstance(ticket_id, str) or ticket_id == "":
        raise ApiError("ERR_VALIDATION", 422, "repair_ticket_id is required")
    if not isinstance(customer_id, str) or customer_id == "":
        raise ApiError("ERR_VALIDATION", 422, "customer_id is required")
    get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    get_or_404(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    plan_type = v_enum(body, "plan_type", PLAN_TYPES)
    rec = base_record()
    rec.update({
        "repair_ticket_id": ticket_id,
        "customer_id": customer_id,
        "plan_type": plan_type,
        "routing_destination": None,
        "deductible_cents": DEDUCTIBLE_BY_PLAN[plan_type],
        "covered_amount_cents": None,
        "status": "FILED",
    })
    db.claims[rec["id"]] = rec
    return obj(rec, status=201)


@app.route("/protection-plan-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    require_auth()
    require_role(*ROLES)
    return obj(get_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND"))


@app.route("/protection-plan-claims", methods=["GET"])
def list_claims():
    require_auth()
    require_role(*ROLES)
    records = list(db.claims.values())
    for field in ("repair_ticket_id", "customer_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    page, pg = paginate(records)
    return arr(page, pg)


@app.route("/protection-plan-claims/<claim_id>/route", methods=["POST"])
def route_claim(claim_id):
    require_auth()
    require_role("ServiceAdvisor")
    claim = get_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "claim not FILED")
    claim["routing_destination"] = ROUTING_BY_PLAN[claim["plan_type"]]
    claim["status"] = "ROUTED"
    touch(claim)
    return obj(claim, status=200)


@app.route("/protection-plan-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    require_auth()
    require_role("StoreManager")
    claim = get_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "ROUTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "claim not ROUTED")
    estimate = approved_estimate(claim["repair_ticket_id"])
    if estimate is None:
        raise ApiError("ERR_ESTIMATE_NOT_APPROVED", 409, "no approved/finalized estimate")
    if estimate["status"] == "FINALIZED" and estimate["final_total_cents"] is not None:
        estimate_total_cents = estimate["final_total_cents"]
    else:
        estimate_total_cents = estimate["provisional_total_cents"]
    covered = max(0, min(estimate_total_cents - claim["deductible_cents"], COVERAGE_CAP_CENTS))
    claim["covered_amount_cents"] = covered
    claim["status"] = "APPROVED"
    touch(claim)
    return obj(claim, status=200)


@app.route("/protection-plan-claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    require_auth()
    require_role("StoreManager")
    claim = get_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "ROUTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "claim not ROUTED")
    claim["status"] = "DENIED"
    touch(claim)
    return obj(claim, status=200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
