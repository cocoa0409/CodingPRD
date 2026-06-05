"""Commercial Fleet Leasing API.

Single-file Flask implementation. In-memory storage only; state resets on every
process start. No disk persistence, no seeding.

Authoritative spec: workspace/PRD.md (prose wins over SCAFFOLD.yaml).
"""

import os
import re
import uuid
import random
import string
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLES = {"FleetManager", "Lessee", "ComplianceOfficer", "TelematicsGateway"}

JURISDICTIONS = ["CA", "NV", "AZ", "OR", "TX", "WA"]
IFTA_RATE = {
    "CA": Decimal("0.40"),
    "NV": Decimal("0.27"),
    "AZ": Decimal("0.26"),
    "OR": Decimal("0.38"),
    "TX": Decimal("0.20"),
    "WA": Decimal("0.49"),
}

VEHICLE_CLASSES = {"LIGHT_DUTY", "MEDIUM_DUTY", "HEAVY_DUTY"}
OVERAGE_MODELS = {"CONTRACT_FLAT", "TIERED_EXCESS"}
WATERFALL_MODELS = {"DEDUCTIBLE_FIRST", "INSURANCE_FIRST"}
MAINT_KINDS = {"PREVENTIVE", "CORRECTIVE", "RECALL"}

TIER1_LIMIT_MILES = 10000
TIER1_RATE_CENTS = 20
TIER2_RATE_CENTS = 35

W_HARSH = Decimal("0.5")
W_IDLE = Decimal("0.3")
W_SPEED = Decimal("0.2")
WEAR_THRESHOLD = Decimal("30")
EXCESS_WEAR_FLAT_CENTS = 50000

TOTAL_LOSS_RATIO = Decimal("0.8")
MAINT_BUFFER_MINUTES = 60

QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.lessees = {}
        self.drivers = {}
        self.vehicles = {}
        self.leases = {}
        self.allocations = {}
        self.fuel_cards = {}
        self.fuel_transactions = {}
        self.telematics = {}
        self.maintenance_orders = {}
        self.repair_orders = {}
        self.settlements = {}
        self.ifta_returns = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


store = Store()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, http_status, error_id, message=""):
        super().__init__(message)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message or error_id


def err(http_status, error_id, message=""):
    raise ApiError(http_status, error_id, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _meta(extra=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": now_ts()}
    if extra:
        m.update(extra)
    return m


def respond_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), code


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            err(422, "ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return data
    return {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err(422, "ERR_INVALID_REQUEST", f"{field} is required and must be a non-empty string")
    return v


def req_nonneg_int(body, field):
    if field not in body:
        err(422, "ERR_INVALID_REQUEST", f"{field} is required")
    v = body.get(field)
    if not is_int(v) or v < 0:
        err(422, "ERR_INVALID_REQUEST", f"{field} must be a non-negative integer")
    return v


def req_int(body, field):
    if field not in body:
        err(422, "ERR_INVALID_REQUEST", f"{field} is required")
    v = body.get(field)
    if not is_int(v):
        err(422, "ERR_INVALID_REQUEST", f"{field} must be an integer")
    return v


def opt_nonneg_int(body, field, default=0):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not is_int(v) or v < 0:
        err(422, "ERR_INVALID_REQUEST", f"{field} must be a non-negative integer")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        err(422, "ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err(422, "ERR_INVALID_REQUEST", f"{field} is required and must be an ISO 8601 string")
    if parse_dt(v) is None:
        err(422, "ERR_INVALID_REQUEST", f"{field} must be a valid ISO 8601 datetime")
    return v


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        err(401, "ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    g.user_id = user_id
    g.role = role
    return role, user_id


def authorize(allowed_roles):
    role, user_id = authenticate()
    if role not in allowed_roles:
        err(403, "ERR_FORBIDDEN", "Role not permitted for this operation")
    return role, user_id


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_lessee(o):
    return {
        "id": o["id"],
        "company_name": o["company_name"],
        "billing_email": o["billing_email"],
        "account_status": o["account_status"],
        "outstanding_balance_cents": o["outstanding_balance_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_driver(o):
    return {
        "id": o["id"],
        "lessee_id": o["lessee_id"],
        "full_name": o["full_name"],
        "license_number": o["license_number"],
        "license_status": o["license_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_vehicle(o):
    return {
        "id": o["id"],
        "vin": o["vin"],
        "class": o["class"],
        "status": o["status"],
        "odometer_miles": o["odometer_miles"],
        "open_block_count": o["open_block_count"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_lease(o):
    return {
        "id": o["id"],
        "lessee_id": o["lessee_id"],
        "vehicle_id": o["vehicle_id"],
        "status": o["status"],
        "term_start": o["term_start"],
        "term_end": o["term_end"],
        "contracted_miles": o["contracted_miles"],
        "per_mile_overage_cents": o["per_mile_overage_cents"],
        "overage_model": o["overage_model"],
        "collision_deductible_cents": o["collision_deductible_cents"],
        "waterfall_model": o["waterfall_model"],
        "odometer_start": o["odometer_start"],
        "odometer_end": o["odometer_end"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_allocation(o):
    return {
        "id": o["id"],
        "lease_id": o["lease_id"],
        "driver_id": o["driver_id"],
        "status": o["status"],
        "window_start": o["window_start"],
        "window_end": o["window_end"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_fuel_card(o):
    return {
        "id": o["id"],
        "lease_id": o["lease_id"],
        "card_number": o["card_number"],
        "status": o["status"],
        "total_gallons_purchased": o["total_gallons_purchased"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_fuel_txn(o):
    return {
        "id": o["id"],
        "fuel_card_id": o["fuel_card_id"],
        "jurisdiction": o["jurisdiction"],
        "gallons": o["gallons"],
        "purchased_at": o["purchased_at"],
        "status": o["status"],
        "created_at": o["created_at"],
    }


def ser_telematics(o):
    return {
        "id": o["id"],
        "vehicle_id": o["vehicle_id"],
        "jurisdiction": o["jurisdiction"],
        "odometer_miles": o["odometer_miles"],
        "segment_miles": o["segment_miles"],
        "harsh_events": o["harsh_events"],
        "idle_minutes": o["idle_minutes"],
        "recorded_at": o["recorded_at"],
        "created_at": o["created_at"],
    }


def ser_maint(o):
    return {
        "id": o["id"],
        "vehicle_id": o["vehicle_id"],
        "kind": o["kind"],
        "window_start": o["window_start"],
        "window_end": o["window_end"],
        "status": o["status"],
        "labor_cents": o["labor_cents"],
        "parts_cents": o["parts_cents"],
        "total_cost_cents": o["total_cost_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_repair(o):
    return {
        "id": o["id"],
        "vehicle_id": o["vehicle_id"],
        "lease_id": o["lease_id"],
        "status": o["status"],
        "estimate_cents": o["estimate_cents"],
        "insurance_cap_cents": o["insurance_cap_cents"],
        "driver_deductible_cents": o["driver_deductible_cents"],
        "insurance_paid_cents": o["insurance_paid_cents"],
        "lessee_responsible_cents": o["lessee_responsible_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_settlement(o):
    return {
        "id": o["id"],
        "lease_id": o["lease_id"],
        "status": o["status"],
        "excess_miles": o["excess_miles"],
        "mileage_charge_cents": o["mileage_charge_cents"],
        "excess_wear_score": o["excess_wear_score"],
        "excess_wear_charge_cents": o["excess_wear_charge_cents"],
        "net_charge_cents": o["net_charge_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_ifta(o):
    return {
        "id": o["id"],
        "lessee_id": o["lessee_id"],
        "quarter": o["quarter"],
        "status": o["status"],
        "fleet_mpg": o["fleet_mpg"],
        "net_tax_due_cents": o["net_tax_due_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def touch(o):
    o["updated_at"] = now_ts()
    o["version"] = o["version"] + 1


def base_common():
    ts = now_ts()
    return {"id": store.new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": store.next_seq()}


def base_append():
    ts = now_ts()
    return {"id": store.new_id(), "created_at": ts, "_seq": store.next_seq()}


def paginate(items):
    # items already sorted by created_at asc (use _seq)
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def compute_open_block_count(vehicle_id):
    count = 0
    for m in store.maintenance_orders.values():
        if m["vehicle_id"] == vehicle_id and m["status"] in ("SCHEDULED", "IN_PROGRESS"):
            count += 1
    for r in store.repair_orders.values():
        if r["vehicle_id"] == vehicle_id and r["status"] not in (
                "COMPLETED", "TOTAL_LOSS_SETTLED", "REJECTED"):
            count += 1
    return count


def quarter_of(dt):
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{q}"


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return respond_error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return respond_error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return respond_error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ----------------------------- Lessees -------------------------------------

@app.post("/fleet/lessees")
def create_lessee():
    authorize({"FleetManager"})
    body = get_body()
    company_name = req_str(body, "company_name")
    billing_email = req_str(body, "billing_email")
    with store.lock:
        o = base_common()
        o.update({
            "company_name": company_name,
            "billing_email": billing_email,
            "account_status": "ACTIVE",
            "outstanding_balance_cents": 0,
        })
        store.lessees[o["id"]] = o
        return respond_object(ser_lessee(o), 201)


@app.get("/fleet/lessees/<id>")
def get_lessee(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        o = store.lessees.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Lessee not found")
        return respond_object(ser_lessee(o), 200)


@app.post("/fleet/lessees/<id>/suspend")
def suspend_lessee(id):
    authorize({"FleetManager"})
    with store.lock:
        o = store.lessees.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Lessee not found")
        o["account_status"] = "SUSPENDED"
        touch(o)
        return respond_object(ser_lessee(o), 200)


# ----------------------------- Drivers -------------------------------------

@app.post("/fleet/drivers")
def create_driver():
    authorize({"FleetManager", "Lessee"})
    body = get_body()
    lessee_id = req_str(body, "lessee_id")
    full_name = req_str(body, "full_name")
    license_number = req_str(body, "license_number")
    with store.lock:
        if lessee_id not in store.lessees:
            err(404, "ERR_NOT_FOUND", "Lessee not found")
        for d in store.drivers.values():
            if d["license_number"] == license_number:
                err(409, "ERR_DUPLICATE", "license_number already used")
        o = base_common()
        o.update({
            "lessee_id": lessee_id,
            "full_name": full_name,
            "license_number": license_number,
            "license_status": "VALID",
        })
        store.drivers[o["id"]] = o
        return respond_object(ser_driver(o), 201)


@app.get("/fleet/drivers/<id>")
def get_driver(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        o = store.drivers.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Driver not found")
        return respond_object(ser_driver(o), 200)


@app.get("/fleet/drivers")
def list_drivers():
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    lessee_id = request.args.get("lessee_id")
    with store.lock:
        items = sorted(store.drivers.values(), key=lambda x: x["_seq"])
        if lessee_id is not None:
            items = [d for d in items if d["lessee_id"] == lessee_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_driver(d) for d in page], limit, offset, total)


@app.post("/fleet/drivers/<id>/suspend-license")
def suspend_license(id):
    authorize({"FleetManager"})
    with store.lock:
        o = store.drivers.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Driver not found")
        o["license_status"] = "SUSPENDED"
        touch(o)
        return respond_object(ser_driver(o), 200)


# ----------------------------- Vehicles ------------------------------------

@app.post("/fleet/vehicles")
def create_vehicle():
    authorize({"FleetManager"})
    body = get_body()
    vin = req_str(body, "vin")
    vclass = req_enum(body, "class", VEHICLE_CLASSES)
    with store.lock:
        for v in store.vehicles.values():
            if v["vin"] == vin:
                err(409, "ERR_DUPLICATE", "vin already used")
        o = base_common()
        o.update({
            "vin": vin,
            "class": vclass,
            "status": "AVAILABLE",
            "odometer_miles": 0,
            "open_block_count": 0,
        })
        store.vehicles[o["id"]] = o
        return respond_object(ser_vehicle(o), 201)


def _get_vehicle(id):
    v = store.vehicles.get(id)
    if v is None:
        err(404, "ERR_NOT_FOUND", "Vehicle not found")
    return v


@app.get("/fleet/vehicles/<id>")
def get_vehicle(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        return respond_object(ser_vehicle(_get_vehicle(id)), 200)


@app.get("/fleet/vehicles/<id>/telematics-readings")
def list_vehicle_telematics(id):
    authorize({"FleetManager", "ComplianceOfficer", "TelematicsGateway"})
    with store.lock:
        _get_vehicle(id)
        items = sorted(
            [t for t in store.telematics.values() if t["vehicle_id"] == id],
            key=lambda x: x["_seq"])
        page, limit, offset, total = paginate(items)
        return respond_array([ser_telematics(t) for t in page], limit, offset, total)


@app.get("/fleet/vehicles/<id>/maintenance-orders")
def list_vehicle_maintenance(id):
    authorize({"FleetManager", "Lessee"})
    with store.lock:
        _get_vehicle(id)
        items = sorted(
            [m for m in store.maintenance_orders.values() if m["vehicle_id"] == id],
            key=lambda x: x["_seq"])
        page, limit, offset, total = paginate(items)
        return respond_array([ser_maint(m) for m in page], limit, offset, total)


# ----------------------------- Leases --------------------------------------

@app.post("/fleet/leases")
def create_lease():
    authorize({"FleetManager"})
    body = get_body()
    lessee_id = req_str(body, "lessee_id")
    vehicle_id = req_str(body, "vehicle_id")
    with store.lock:
        # existence FKs left-to-right (lessee_id, vehicle_id)
        if lessee_id not in store.lessees:
            err(404, "ERR_NOT_FOUND", "Lessee not found")
        if vehicle_id not in store.vehicles:
            err(404, "ERR_NOT_FOUND", "Vehicle not found")
        term_start = req_datetime(body, "term_start")
        term_end = req_datetime(body, "term_end")
        contracted_miles = req_nonneg_int(body, "contracted_miles")
        per_mile_overage_cents = req_nonneg_int(body, "per_mile_overage_cents")
        overage_model = req_enum(body, "overage_model", OVERAGE_MODELS)
        collision_deductible_cents = req_nonneg_int(body, "collision_deductible_cents")
        waterfall_model = req_enum(body, "waterfall_model", WATERFALL_MODELS)
        o = base_common()
        o.update({
            "lessee_id": lessee_id,
            "vehicle_id": vehicle_id,
            "status": "DRAFT",
            "term_start": term_start,
            "term_end": term_end,
            "contracted_miles": contracted_miles,
            "per_mile_overage_cents": per_mile_overage_cents,
            "overage_model": overage_model,
            "collision_deductible_cents": collision_deductible_cents,
            "waterfall_model": waterfall_model,
            "odometer_start": 0,
            "odometer_end": 0,
        })
        store.leases[o["id"]] = o
        return respond_object(ser_lease(o), 201)


def _get_lease(id):
    o = store.leases.get(id)
    if o is None:
        err(404, "ERR_NOT_FOUND", "Lease not found")
    return o


@app.get("/fleet/leases/<id>")
def get_lease(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        return respond_object(ser_lease(_get_lease(id)), 200)


@app.get("/fleet/leases")
def list_leases():
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    lessee_id = request.args.get("lessee_id")
    vehicle_id = request.args.get("vehicle_id")
    with store.lock:
        items = sorted(store.leases.values(), key=lambda x: x["_seq"])
        if lessee_id is not None:
            items = [l for l in items if l["lessee_id"] == lessee_id]
        if vehicle_id is not None:
            items = [l for l in items if l["vehicle_id"] == vehicle_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_lease(l) for l in page], limit, offset, total)


@app.post("/fleet/leases/<id>/activate")
def activate_lease(id):
    authorize({"FleetManager"})
    with store.lock:
        l = _get_lease(id)
        if l["status"] != "DRAFT":
            err(409, "ERR_INVALID_STATE", "Lease is not DRAFT")
        v = store.vehicles.get(l["vehicle_id"])
        lessee = store.lessees.get(l["lessee_id"])
        if v is None or v["status"] != "AVAILABLE":
            err(409, "ERR_VEHICLE_NOT_AVAILABLE", "Vehicle is not AVAILABLE")
        # lessee account must be ACTIVE (no dedicated error code -> ERR_INVALID_STATE)
        if lessee is not None and lessee["account_status"] != "ACTIVE":
            err(409, "ERR_INVALID_STATE", "Lessee account is not ACTIVE")
        l["odometer_start"] = v["odometer_miles"]
        l["status"] = "ACTIVE"
        touch(l)
        v["status"] = "ALLOCATED"
        touch(v)
        return respond_object(ser_lease(l), 200)


@app.post("/fleet/leases/<id>/cancel")
def cancel_lease(id):
    authorize({"FleetManager"})
    with store.lock:
        l = _get_lease(id)
        if l["status"] != "DRAFT":
            err(409, "ERR_INVALID_STATE", "Lease is not DRAFT")
        l["status"] = "CANCELLED"
        touch(l)
        return respond_object(ser_lease(l), 200)


@app.post("/fleet/leases/<id>/initiate-return")
def initiate_return(id):
    authorize({"FleetManager"})
    with store.lock:
        l = _get_lease(id)
        if l["status"] != "ACTIVE":
            err(409, "ERR_INVALID_STATE", "Lease is not ACTIVE")
        for a in store.allocations.values():
            if a["lease_id"] == id and a["status"] == "ASSIGNED":
                err(409, "ERR_ACTIVE_ALLOCATION_EXISTS",
                    "An allocation on this lease is still ASSIGNED")
        v = store.vehicles.get(l["vehicle_id"])
        l["odometer_end"] = v["odometer_miles"] if v else 0
        l["status"] = "RETURN_INITIATED"
        touch(l)
        # freeze ACTIVE fuel cards
        for c in store.fuel_cards.values():
            if c["lease_id"] == id and c["status"] == "ACTIVE":
                c["status"] = "FROZEN"
                touch(c)
        return respond_object(ser_lease(l), 200)


# ----------------------------- Allocations ---------------------------------

@app.post("/fleet/allocations")
def create_allocation():
    authorize({"FleetManager"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    driver_id = req_str(body, "driver_id")
    with store.lock:
        # existence FKs left-to-right
        l = store.leases.get(lease_id)
        if l is None:
            err(404, "ERR_NOT_FOUND", "Lease not found")
        d = store.drivers.get(driver_id)
        if d is None:
            err(404, "ERR_NOT_FOUND", "Driver not found")
        window_start = req_datetime(body, "window_start")
        window_end = req_datetime(body, "window_end")
        # expected_lease_version required, well-typed
        if "expected_lease_version" not in body:
            err(422, "ERR_INVALID_REQUEST", "expected_lease_version is required")
        elv = body.get("expected_lease_version")
        if not is_int(elv):
            err(422, "ERR_INVALID_REQUEST", "expected_lease_version must be an integer")
        # business: driver license valid, lease active, overlap
        if d["license_status"] != "VALID":
            err(409, "ERR_DRIVER_LICENSE_INVALID", "Driver license is not VALID")
        if l["status"] != "ACTIVE":
            err(409, "ERR_LEASE_NOT_ACTIVE", "Lease is not ACTIVE")
        # overlap against ASSIGNED allocations on the same lease's vehicle
        ws = parse_dt(window_start)
        we = parse_dt(window_end)
        vehicle_id = l["vehicle_id"]
        for a in store.allocations.values():
            if a["status"] != "ASSIGNED":
                continue
            other_lease = store.leases.get(a["lease_id"])
            if other_lease is None or other_lease["vehicle_id"] != vehicle_id:
                continue
            aws = parse_dt(a["window_start"])
            awe = parse_dt(a["window_end"])
            # half-open overlap: [ws,we) overlaps [aws,awe) iff ws < awe and aws < we
            if ws < awe and aws < we:
                err(409, "ERR_ALLOCATION_OVERLAP", "Allocation window overlaps existing")
        # OCC last
        if elv != l["version"]:
            err(412, "ERR_STALE_VERSION", "expected_lease_version mismatch")
        o = base_common()
        o.update({
            "lease_id": lease_id,
            "driver_id": driver_id,
            "status": "ASSIGNED",
            "window_start": window_start,
            "window_end": window_end,
        })
        store.allocations[o["id"]] = o
        touch(l)  # increments lease version
        return respond_object(ser_allocation(o), 201)


@app.get("/fleet/allocations/<id>")
def get_allocation(id):
    authorize({"FleetManager", "Lessee"})
    with store.lock:
        o = store.allocations.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Allocation not found")
        return respond_object(ser_allocation(o), 200)


@app.get("/fleet/allocations")
def list_allocations():
    authorize({"FleetManager", "Lessee"})
    lease_id = request.args.get("lease_id")
    driver_id = request.args.get("driver_id")
    with store.lock:
        items = sorted(store.allocations.values(), key=lambda x: x["_seq"])
        if lease_id is not None:
            items = [a for a in items if a["lease_id"] == lease_id]
        if driver_id is not None:
            items = [a for a in items if a["driver_id"] == driver_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_allocation(a) for a in page], limit, offset, total)


@app.post("/fleet/allocations/<id>/release")
def release_allocation(id):
    authorize({"FleetManager"})
    with store.lock:
        o = store.allocations.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Allocation not found")
        if o["status"] != "ASSIGNED":
            err(409, "ERR_INVALID_STATE", "Allocation is not ASSIGNED")
        o["status"] = "RELEASED"
        touch(o)
        return respond_object(ser_allocation(o), 200)


# ----------------------------- Fuel Cards ----------------------------------

@app.post("/fleet/fuel-cards")
def create_fuel_card():
    authorize({"FleetManager"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    card_number = req_str(body, "card_number")
    with store.lock:
        if lease_id not in store.leases:
            err(404, "ERR_NOT_FOUND", "Lease not found")
        for c in store.fuel_cards.values():
            if c["card_number"] == card_number:
                err(409, "ERR_DUPLICATE", "card_number already used")
        o = base_common()
        o.update({
            "lease_id": lease_id,
            "card_number": card_number,
            "status": "ACTIVE",
            "total_gallons_purchased": 0,
        })
        store.fuel_cards[o["id"]] = o
        return respond_object(ser_fuel_card(o), 201)


@app.get("/fleet/fuel-cards/<id>")
def get_fuel_card(id):
    authorize({"FleetManager", "Lessee"})
    with store.lock:
        o = store.fuel_cards.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Fuel card not found")
        return respond_object(ser_fuel_card(o), 200)


@app.get("/fleet/fuel-cards")
def list_fuel_cards():
    authorize({"FleetManager", "Lessee"})
    lease_id = request.args.get("lease_id")
    with store.lock:
        items = sorted(store.fuel_cards.values(), key=lambda x: x["_seq"])
        if lease_id is not None:
            items = [c for c in items if c["lease_id"] == lease_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_fuel_card(c) for c in page], limit, offset, total)


# ----------------------------- Fuel Transactions ---------------------------

@app.post("/fleet/fuel-transactions")
def create_fuel_txn():
    authorize({"FleetManager", "Lessee"})
    body = get_body()
    fuel_card_id = req_str(body, "fuel_card_id")
    with store.lock:
        card = store.fuel_cards.get(fuel_card_id)
        if card is None:
            err(404, "ERR_NOT_FOUND", "Fuel card not found")
        jurisdiction = req_enum(body, "jurisdiction", set(JURISDICTIONS))
        if "gallons" not in body:
            err(422, "ERR_INVALID_REQUEST", "gallons is required")
        gallons = body.get("gallons")
        if not is_number(gallons) or gallons <= 0:
            err(422, "ERR_INVALID_REQUEST", "gallons must be a number > 0")
        purchased_at = req_datetime(body, "purchased_at")
        if card["status"] != "ACTIVE":
            err(409, "ERR_FUEL_CARD_NOT_ACTIVE", "Fuel card is not ACTIVE")
        o = base_append()
        o.update({
            "fuel_card_id": fuel_card_id,
            "jurisdiction": jurisdiction,
            "gallons": gallons,
            "purchased_at": purchased_at,
            "status": "POSTED",
        })
        store.fuel_transactions[o["id"]] = o
        card["total_gallons_purchased"] = card["total_gallons_purchased"] + gallons
        touch(card)
        return respond_object(ser_fuel_txn(o), 201)


@app.get("/fleet/fuel-transactions/<id>")
def get_fuel_txn(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        o = store.fuel_transactions.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Fuel transaction not found")
        return respond_object(ser_fuel_txn(o), 200)


@app.get("/fleet/fuel-transactions")
def list_fuel_txns():
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    fuel_card_id = request.args.get("fuel_card_id")
    with store.lock:
        items = sorted(store.fuel_transactions.values(), key=lambda x: x["_seq"])
        if fuel_card_id is not None:
            items = [t for t in items if t["fuel_card_id"] == fuel_card_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_fuel_txn(t) for t in page], limit, offset, total)


@app.post("/fleet/fuel-transactions/<id>/void")
def void_fuel_txn(id):
    authorize({"FleetManager"})
    with store.lock:
        o = store.fuel_transactions.get(id)
        if o is None:
            err(404, "ERR_NOT_FOUND", "Fuel transaction not found")
        if o["status"] != "POSTED":
            err(409, "ERR_INVALID_STATE", "Fuel transaction is not POSTED")
        o["status"] = "VOIDED"
        card = store.fuel_cards.get(o["fuel_card_id"])
        if card is not None:
            card["total_gallons_purchased"] = card["total_gallons_purchased"] - o["gallons"]
            touch(card)
        return respond_object(ser_fuel_txn(o), 200)


# ----------------------------- Telematics ----------------------------------

@app.post("/fleet/telematics-readings")
def create_telematics():
    authorize({"TelematicsGateway", "FleetManager"})
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    with store.lock:
        v = store.vehicles.get(vehicle_id)
        if v is None:
            err(404, "ERR_NOT_FOUND", "Vehicle not found")
        jurisdiction = req_enum(body, "jurisdiction", set(JURISDICTIONS))
        odometer_miles = req_nonneg_int(body, "odometer_miles")
        segment_miles = req_nonneg_int(body, "segment_miles")
        harsh_events = opt_nonneg_int(body, "harsh_events", 0)
        idle_minutes = opt_nonneg_int(body, "idle_minutes", 0)
        recorded_at = req_datetime(body, "recorded_at")
        if odometer_miles < v["odometer_miles"]:
            err(409, "ERR_ODOMETER_REGRESSION", "odometer_miles below current")
        o = base_append()
        o.update({
            "vehicle_id": vehicle_id,
            "jurisdiction": jurisdiction,
            "odometer_miles": odometer_miles,
            "segment_miles": segment_miles,
            "harsh_events": harsh_events,
            "idle_minutes": idle_minutes,
            "recorded_at": recorded_at,
        })
        store.telematics[o["id"]] = o
        v["odometer_miles"] = odometer_miles
        touch(v)
        return respond_object(ser_telematics(o), 201)


# ----------------------------- Maintenance ---------------------------------

@app.post("/fleet/maintenance-orders")
def create_maintenance():
    authorize({"FleetManager"})
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    with store.lock:
        v = store.vehicles.get(vehicle_id)
        if v is None:
            err(404, "ERR_NOT_FOUND", "Vehicle not found")
        kind = req_enum(body, "kind", MAINT_KINDS)
        labor_cents = req_nonneg_int(body, "labor_cents")
        parts_cents = req_nonneg_int(body, "parts_cents")
        window_start = req_datetime(body, "window_start")
        window_end = req_datetime(body, "window_end")
        # buffered overlap: expand by 60 min on each end; conflict if gap <= 60 min
        ws = parse_dt(window_start)
        we = parse_dt(window_end)
        buf = MAINT_BUFFER_MINUTES * 60
        for m in store.maintenance_orders.values():
            if m["vehicle_id"] != vehicle_id:
                continue
            if m["status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            ows = parse_dt(m["window_start"])
            owe = parse_dt(m["window_end"])
            # expanded new window overlaps existing closed window if
            # (ws - buf) <= owe and ows <= (we + buf)
            new_start = ws.timestamp() - buf
            new_end = we.timestamp() + buf
            if new_start <= owe.timestamp() and ows.timestamp() <= new_end:
                err(409, "ERR_MAINTENANCE_OVERLAP", "Maintenance window collides")
        o = base_common()
        o.update({
            "vehicle_id": vehicle_id,
            "kind": kind,
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "labor_cents": labor_cents,
            "parts_cents": parts_cents,
            "total_cost_cents": 0,
        })
        store.maintenance_orders[o["id"]] = o
        return respond_object(ser_maint(o), 201)


def _get_maint(id):
    o = store.maintenance_orders.get(id)
    if o is None:
        err(404, "ERR_NOT_FOUND", "Maintenance order not found")
    return o


@app.get("/fleet/maintenance-orders/<id>")
def get_maintenance(id):
    authorize({"FleetManager", "Lessee"})
    with store.lock:
        return respond_object(ser_maint(_get_maint(id)), 200)


@app.post("/fleet/maintenance-orders/<id>/start")
def start_maintenance(id):
    authorize({"FleetManager"})
    with store.lock:
        m = _get_maint(id)
        if m["status"] != "SCHEDULED":
            err(409, "ERR_INVALID_STATE", "Maintenance order is not SCHEDULED")
        v = store.vehicles.get(m["vehicle_id"])
        if v is None or v["status"] not in ("ALLOCATED", "IN_MAINTENANCE"):
            err(409, "ERR_INVALID_STATE", "Vehicle not in ALLOCATED/IN_MAINTENANCE")
        m["status"] = "IN_PROGRESS"
        touch(m)
        v["open_block_count"] = v["open_block_count"] + 1
        if v["status"] == "ALLOCATED":
            v["status"] = "IN_MAINTENANCE"
        touch(v)
        return respond_object(ser_maint(m), 200)


@app.post("/fleet/maintenance-orders/<id>/complete")
def complete_maintenance(id):
    authorize({"FleetManager"})
    with store.lock:
        m = _get_maint(id)
        if m["status"] != "IN_PROGRESS":
            err(409, "ERR_INVALID_STATE", "Maintenance order is not IN_PROGRESS")
        m["total_cost_cents"] = m["labor_cents"] + m["parts_cents"]
        m["status"] = "COMPLETED"
        touch(m)
        v = store.vehicles.get(m["vehicle_id"])
        if v is not None:
            v["open_block_count"] = max(0, v["open_block_count"] - 1)
            if v["open_block_count"] == 0 and v["status"] == "IN_MAINTENANCE":
                v["status"] = "ALLOCATED"
            touch(v)
        return respond_object(ser_maint(m), 200)


@app.post("/fleet/maintenance-orders/<id>/cancel")
def cancel_maintenance(id):
    authorize({"FleetManager"})
    with store.lock:
        m = _get_maint(id)
        if m["status"] != "SCHEDULED":
            err(409, "ERR_INVALID_STATE", "Maintenance order is not SCHEDULED")
        m["status"] = "CANCELLED"
        touch(m)
        return respond_object(ser_maint(m), 200)


# ----------------------------- Repair Orders -------------------------------

@app.post("/fleet/repair-orders")
def create_repair():
    authorize({"FleetManager"})
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    lease_id = req_str(body, "lease_id")
    with store.lock:
        v = store.vehicles.get(vehicle_id)
        if v is None:
            err(404, "ERR_NOT_FOUND", "Vehicle not found")
        l = store.leases.get(lease_id)
        if l is None:
            err(404, "ERR_NOT_FOUND", "Lease not found")
        if "expected_vehicle_version" not in body:
            err(422, "ERR_INVALID_REQUEST", "expected_vehicle_version is required")
        evv = body.get("expected_vehicle_version")
        if not is_int(evv):
            err(422, "ERR_INVALID_REQUEST", "expected_vehicle_version must be an integer")
        if evv != v["version"]:
            err(412, "ERR_STALE_VERSION", "expected_vehicle_version mismatch")
        o = base_common()
        o.update({
            "vehicle_id": vehicle_id,
            "lease_id": lease_id,
            "status": "REPORTED",
            "estimate_cents": 0,
            "insurance_cap_cents": 0,
            "driver_deductible_cents": 0,
            "insurance_paid_cents": 0,
            "lessee_responsible_cents": 0,
        })
        store.repair_orders[o["id"]] = o
        touch(v)  # increments vehicle version
        return respond_object(ser_repair(o), 201)


def _get_repair(id):
    o = store.repair_orders.get(id)
    if o is None:
        err(404, "ERR_NOT_FOUND", "Repair order not found")
    return o


@app.get("/fleet/repair-orders/<id>")
def get_repair(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        return respond_object(ser_repair(_get_repair(id)), 200)


@app.get("/fleet/repair-orders")
def list_repairs():
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    vehicle_id = request.args.get("vehicle_id")
    lease_id = request.args.get("lease_id")
    with store.lock:
        items = sorted(store.repair_orders.values(), key=lambda x: x["_seq"])
        if vehicle_id is not None:
            items = [r for r in items if r["vehicle_id"] == vehicle_id]
        if lease_id is not None:
            items = [r for r in items if r["lease_id"] == lease_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_repair(r) for r in page], limit, offset, total)


def run_waterfall(repair, lease):
    estimate = repair["estimate_cents"]
    cap = repair["insurance_cap_cents"]
    deductible = lease["collision_deductible_cents"]
    if lease["waterfall_model"] == "DEDUCTIBLE_FIRST":
        driver_deductible = min(estimate, deductible)
        remaining = estimate - driver_deductible
        insurance_paid = min(remaining, cap)
        overflow = remaining - insurance_paid
    else:  # INSURANCE_FIRST
        insurance_paid = min(estimate, cap)
        remaining = estimate - insurance_paid
        driver_deductible = min(remaining, deductible)
        overflow = remaining - driver_deductible
    lessee_responsible = driver_deductible + overflow
    repair["driver_deductible_cents"] = driver_deductible
    repair["insurance_paid_cents"] = insurance_paid
    repair["lessee_responsible_cents"] = lessee_responsible


@app.post("/fleet/repair-orders/<id>/assess")
def assess_repair(id):
    authorize({"FleetManager"})
    body = get_body()
    with store.lock:
        r = _get_repair(id)
        if r["status"] != "REPORTED":
            err(409, "ERR_INVALID_STATE", "Repair order is not REPORTED")
        estimate_cents = req_nonneg_int(body, "estimate_cents")
        insurance_cap_cents = req_nonneg_int(body, "insurance_cap_cents")
        r["estimate_cents"] = estimate_cents
        r["insurance_cap_cents"] = insurance_cap_cents
        r["status"] = "ASSESSED"
        touch(r)
        v = store.vehicles.get(r["vehicle_id"])
        if v is not None:
            v["open_block_count"] = v["open_block_count"] + 1
            touch(v)
        return respond_object(ser_repair(r), 200)


@app.post("/fleet/repair-orders/<id>/approve")
def approve_repair(id):
    authorize({"FleetManager"})
    with store.lock:
        r = _get_repair(id)
        if r["status"] != "ASSESSED":
            err(409, "ERR_INVALID_STATE", "Repair order is not ASSESSED")
        # not a total loss: estimate <= 0.8 * cap
        if Decimal(r["estimate_cents"]) > TOTAL_LOSS_RATIO * Decimal(r["insurance_cap_cents"]):
            err(409, "ERR_IS_TOTAL_LOSS", "Estimate exceeds total-loss threshold")
        l = store.leases.get(r["lease_id"])
        run_waterfall(r, l)
        r["status"] = "APPROVED"
        touch(r)
        v = store.vehicles.get(r["vehicle_id"])
        if v is not None and v["status"] == "ALLOCATED":
            v["status"] = "IN_REPAIR"
            touch(v)
        return respond_object(ser_repair(r), 200)


@app.post("/fleet/repair-orders/<id>/declare-total-loss")
def declare_total_loss(id):
    authorize({"FleetManager"})
    with store.lock:
        r = _get_repair(id)
        if r["status"] != "ASSESSED":
            err(409, "ERR_INVALID_STATE", "Repair order is not ASSESSED")
        if Decimal(r["estimate_cents"]) <= TOTAL_LOSS_RATIO * Decimal(r["insurance_cap_cents"]):
            err(409, "ERR_NOT_TOTAL_LOSS", "Estimate does not exceed total-loss threshold")
        r["status"] = "TOTAL_LOSS"
        touch(r)
        return respond_object(ser_repair(r), 200)


@app.post("/fleet/repair-orders/<id>/complete")
def complete_repair(id):
    authorize({"FleetManager"})
    with store.lock:
        r = _get_repair(id)
        if r["status"] != "APPROVED":
            err(409, "ERR_INVALID_STATE", "Repair order is not APPROVED")
        r["status"] = "COMPLETED"
        touch(r)
        v = store.vehicles.get(r["vehicle_id"])
        if v is not None:
            v["open_block_count"] = max(0, v["open_block_count"] - 1)
            if v["open_block_count"] == 0 and v["status"] == "IN_REPAIR":
                v["status"] = "ALLOCATED"
            touch(v)
        return respond_object(ser_repair(r), 200)


@app.post("/fleet/repair-orders/<id>/settle-total-loss")
def settle_total_loss(id):
    authorize({"FleetManager"})
    with store.lock:
        r = _get_repair(id)
        if r["status"] != "TOTAL_LOSS":
            err(409, "ERR_INVALID_STATE", "Repair order is not TOTAL_LOSS")
        l = store.leases.get(r["lease_id"])
        run_waterfall(r, l)
        r["status"] = "TOTAL_LOSS_SETTLED"
        touch(r)
        # add to lessee balance
        if l is not None:
            lessee = store.lessees.get(l["lessee_id"])
            if lessee is not None:
                lessee["outstanding_balance_cents"] = \
                    lessee["outstanding_balance_cents"] + r["lessee_responsible_cents"]
                touch(lessee)
        v = store.vehicles.get(r["vehicle_id"])
        if v is not None:
            v["open_block_count"] = max(0, v["open_block_count"] - 1)
            v["status"] = "RETIRED"
            touch(v)
        return respond_object(ser_repair(r), 200)


@app.post("/fleet/repair-orders/<id>/reject")
def reject_repair(id):
    authorize({"FleetManager"})
    with store.lock:
        r = _get_repair(id)
        if r["status"] != "ASSESSED":
            err(409, "ERR_INVALID_STATE", "Repair order is not ASSESSED")
        r["status"] = "REJECTED"
        touch(r)
        v = store.vehicles.get(r["vehicle_id"])
        if v is not None:
            v["open_block_count"] = max(0, v["open_block_count"] - 1)
            touch(v)
        return respond_object(ser_repair(r), 200)


# ----------------------------- Overage Settlement --------------------------

@app.post("/fleet/overage-settlements")
def create_settlement():
    authorize({"FleetManager"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    with store.lock:
        l = store.leases.get(lease_id)
        if l is None:
            err(404, "ERR_NOT_FOUND", "Lease not found")
        if l["status"] != "RETURN_INITIATED":
            err(409, "ERR_INVALID_STATE", "Lease is not RETURN_INITIATED")
        for s in store.settlements.values():
            if s["lease_id"] == lease_id:
                err(409, "ERR_INVALID_STATE", "Settlement already exists for this lease")
        o = base_common()
        o.update({
            "lease_id": lease_id,
            "status": "DRAFT",
            "excess_miles": 0,
            "mileage_charge_cents": 0,
            "excess_wear_score": 0,
            "excess_wear_charge_cents": 0,
            "net_charge_cents": 0,
        })
        store.settlements[o["id"]] = o
        l["status"] = "PENDING_SETTLEMENT"
        touch(l)
        return respond_object(ser_settlement(o), 201)


def _get_settlement(id):
    o = store.settlements.get(id)
    if o is None:
        err(404, "ERR_NOT_FOUND", "Settlement not found")
    return o


@app.get("/fleet/overage-settlements/<id>")
def get_settlement(id):
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    with store.lock:
        return respond_object(ser_settlement(_get_settlement(id)), 200)


@app.get("/fleet/overage-settlements")
def list_settlements():
    authorize({"FleetManager", "ComplianceOfficer", "Lessee"})
    lease_id = request.args.get("lease_id")
    with store.lock:
        items = sorted(store.settlements.values(), key=lambda x: x["_seq"])
        if lease_id is not None:
            items = [s for s in items if s["lease_id"] == lease_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_settlement(s) for s in page], limit, offset, total)


def compute_mileage_charge(lease):
    excess = max(0, lease["odometer_end"] - lease["odometer_start"] - lease["contracted_miles"])
    if lease["overage_model"] == "CONTRACT_FLAT":
        charge = excess * lease["per_mile_overage_cents"]
    else:  # TIERED_EXCESS
        tier1 = min(excess, TIER1_LIMIT_MILES)
        tier2 = max(0, excess - TIER1_LIMIT_MILES)
        charge = tier1 * TIER1_RATE_CENTS + tier2 * TIER2_RATE_CENTS
    return excess, charge


def compute_wear(lease):
    vehicle_id = lease["vehicle_id"]
    term_start = parse_dt(lease["term_start"])
    term_end = parse_dt(lease["term_end"])
    total_harsh = 0
    total_idle = 0
    for t in store.telematics.values():
        if t["vehicle_id"] != vehicle_id:
            continue
        rec = parse_dt(t["recorded_at"])
        if rec is None:
            continue
        if term_start <= rec <= term_end:
            total_harsh += t["harsh_events"]
            total_idle += t["idle_minutes"]
    total_miles = max(1, lease["odometer_end"] - lease["odometer_start"])
    tm = Decimal(total_miles)
    harsh_per_1k = Decimal(total_harsh) / tm * Decimal(1000)
    idle_pct = Decimal(total_idle) / tm * Decimal(100)
    speed_pct = Decimal(0)
    raw = W_HARSH * (harsh_per_1k * Decimal(10)) + W_IDLE * idle_pct + W_SPEED * speed_pct
    score = round_half_up(raw, 2)
    charge = EXCESS_WEAR_FLAT_CENTS if score > WEAR_THRESHOLD else 0
    return score, charge


@app.post("/fleet/overage-settlements/<id>/finalize")
def finalize_settlement(id):
    authorize({"FleetManager"})
    with store.lock:
        s = _get_settlement(id)
        if s["status"] != "DRAFT":
            err(409, "ERR_INVALID_STATE", "Settlement is not DRAFT")
        l = store.leases.get(s["lease_id"])
        if l is None or l["status"] != "PENDING_SETTLEMENT":
            err(409, "ERR_INVALID_STATE", "Lease is not PENDING_SETTLEMENT")
        v = store.vehicles.get(l["vehicle_id"])
        if v is not None and v["open_block_count"] > 0:
            err(409, "ERR_OPEN_BLOCKERS", "Vehicle has open blockers")
        excess_miles, mileage_charge = compute_mileage_charge(l)
        wear_score, wear_charge = compute_wear(l)
        net = mileage_charge + wear_charge
        s["excess_miles"] = excess_miles
        s["mileage_charge_cents"] = mileage_charge
        s["excess_wear_score"] = float(wear_score)
        s["excess_wear_charge_cents"] = wear_charge
        s["net_charge_cents"] = net
        s["status"] = "FINALIZED"
        touch(s)
        lessee = store.lessees.get(l["lessee_id"])
        if lessee is not None:
            lessee["outstanding_balance_cents"] = lessee["outstanding_balance_cents"] + net
            touch(lessee)
        # cascade lease -> CLOSED, vehicle -> AVAILABLE
        l["status"] = "CLOSED"
        touch(l)
        if v is not None:
            v["status"] = "AVAILABLE"
            touch(v)
        return respond_object(ser_settlement(s), 200)


# ----------------------------- IFTA Returns --------------------------------

@app.post("/fleet/ifta-returns")
def create_ifta():
    authorize({"ComplianceOfficer"})
    body = get_body()
    lessee_id = req_str(body, "lessee_id")
    with store.lock:
        if lessee_id not in store.lessees:
            err(404, "ERR_NOT_FOUND", "Lessee not found")
        quarter = req_str(body, "quarter")
        if not QUARTER_RE.match(quarter):
            err(422, "ERR_INVALID_REQUEST", "quarter must match ^[0-9]{4}Q[1-4]$")
        for r in store.ifta_returns.values():
            if r["lessee_id"] == lessee_id and r["quarter"] == quarter:
                err(409, "ERR_DUPLICATE", "(lessee_id, quarter) already used")
        o = base_common()
        o.update({
            "lessee_id": lessee_id,
            "quarter": quarter,
            "status": "DRAFT",
            "fleet_mpg": 0,
            "net_tax_due_cents": 0,
        })
        store.ifta_returns[o["id"]] = o
        return respond_object(ser_ifta(o), 201)


def _get_ifta(id):
    o = store.ifta_returns.get(id)
    if o is None:
        err(404, "ERR_NOT_FOUND", "IFTA return not found")
    return o


@app.get("/fleet/ifta-returns/<id>")
def get_ifta(id):
    authorize({"ComplianceOfficer", "FleetManager", "Lessee"})
    with store.lock:
        return respond_object(ser_ifta(_get_ifta(id)), 200)


@app.get("/fleet/ifta-returns")
def list_ifta():
    authorize({"ComplianceOfficer", "FleetManager", "Lessee"})
    lessee_id = request.args.get("lessee_id")
    with store.lock:
        items = sorted(store.ifta_returns.values(), key=lambda x: x["_seq"])
        if lessee_id is not None:
            items = [r for r in items if r["lessee_id"] == lessee_id]
        page, limit, offset, total = paginate(items)
        return respond_array([ser_ifta(r) for r in page], limit, offset, total)


def gather_ifta_data(lessee_id, quarter):
    """Return (qualified_miles_total, qualified_gallons_total, miles_by_j, gallons_by_j)."""
    # Qualified vehicles: those that have a lease under this lessee and class in MED/HEAVY.
    # We determine qualified vehicles via leases referencing the lessee.
    qualified_vehicle_ids = set()
    for l in store.leases.values():
        if l["lessee_id"] != lessee_id:
            continue
        v = store.vehicles.get(l["vehicle_id"])
        if v is not None and v["class"] in ("MEDIUM_DUTY", "HEAVY_DUTY"):
            qualified_vehicle_ids.add(v["id"])
    # Telematics: segment_miles for qualified vehicles in quarter (by recorded_at)
    miles_by_j = {j: Decimal(0) for j in JURISDICTIONS}
    total_miles = Decimal(0)
    for t in store.telematics.values():
        if t["vehicle_id"] not in qualified_vehicle_ids:
            continue
        rec = parse_dt(t["recorded_at"])
        if rec is None or quarter_of(rec) != quarter:
            continue
        sm = Decimal(t["segment_miles"])
        total_miles += sm
        miles_by_j[t["jurisdiction"]] += sm
    # Fuel: cards belong to leases of qualified vehicles under this lessee.
    qualified_card_ids = set()
    for c in store.fuel_cards.values():
        l = store.leases.get(c["lease_id"])
        if l is None:
            continue
        if l["lessee_id"] != lessee_id:
            continue
        v = store.vehicles.get(l["vehicle_id"])
        if v is not None and v["class"] in ("MEDIUM_DUTY", "HEAVY_DUTY"):
            qualified_card_ids.add(c["id"])
    gallons_by_j = {j: Decimal(0) for j in JURISDICTIONS}
    total_gallons = Decimal(0)
    for tx in store.fuel_transactions.values():
        if tx["status"] != "POSTED":
            continue
        if tx["fuel_card_id"] not in qualified_card_ids:
            continue
        pa = parse_dt(tx["purchased_at"])
        if pa is None or quarter_of(pa) != quarter:
            continue
        g = Decimal(str(tx["gallons"]))
        total_gallons += g
        gallons_by_j[tx["jurisdiction"]] += g
    return total_miles, total_gallons, miles_by_j, gallons_by_j


@app.post("/fleet/ifta-returns/<id>/file")
def file_ifta(id):
    authorize({"ComplianceOfficer"})
    with store.lock:
        r = _get_ifta(id)
        if r["status"] != "DRAFT":
            err(409, "ERR_INVALID_STATE", "IFTA return is not DRAFT")
        total_miles, total_gallons, miles_by_j, gallons_by_j = \
            gather_ifta_data(r["lessee_id"], r["quarter"])
        if total_gallons <= 0:
            err(409, "ERR_NO_QUALIFIED_FUEL", "No qualified fuel in quarter")
        fleet_mpg = round_half_up(total_miles / total_gallons, 3)
        net_dollars = Decimal(0)
        for j in JURISDICTIONS:
            miles_j = miles_by_j[j]
            gallons_j = gallons_by_j[j]
            if fleet_mpg == 0:
                taxable_gallons_j = Decimal(0)
            else:
                taxable_gallons_j = round_half_up(miles_j / fleet_mpg, 3)
            tax_owed_j = round_half_up(taxable_gallons_j * IFTA_RATE[j], 2)
            tax_paid_j = round_half_up(gallons_j * IFTA_RATE[j], 2)
            net_j = round_half_up(tax_owed_j - tax_paid_j, 2)
            net_dollars += net_j
        net_cents = int(round_half_up(net_dollars * Decimal(100), 0))
        r["fleet_mpg"] = float(fleet_mpg)
        r["net_tax_due_cents"] = net_cents
        r["status"] = "FILED"
        touch(r)
        return respond_object(ser_ifta(r), 200)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
