import os
import math
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =====================================================================
# Constants
# =====================================================================
HOURLY_POOL_RATE_CENTS = 1500
SUBRO_ADMIN_FEE_CENTS = 15000
BAY_BUFFER = timedelta(minutes=60)
FLAG_THRESHOLD = Decimal("70.00")

KNOWN_ROLES = {"FleetAdmin", "MotorPoolClerk", "ShopTech", "FinanceOfficer", "DepartmentUser"}

VEHICLE_CLASSES = {"SEDAN", "PICKUP", "SUV", "HEAVY_TRUCK", "VAN"}
BAY_TYPES = {"GENERAL", "HEAVY", "BODY"}
WO_TYPES = {"PM", "REPAIR", "ACCIDENT_REPAIR"}
ASSIGNMENT_TYPES = {"POOL", "DEPARTMENT_ASSIGNED"}
BASIS_TYPES = {"PROVISIONAL", "FINAL"}
DISPOSITIONS = {"RECOVERED", "RETURN_TO_SERVICE", "WRITE_OFF"}
OUTCOMES = {"REAFFIRM", "ADJUST"}

WO_ACTIVE = {"SCHEDULED", "IN_PROGRESS", "AWAITING_PARTS"}

# =====================================================================
# In-memory store (fresh on every boot)
# =====================================================================
db = {
    "vehicles": {},
    "departments": {},
    "policies": {},
    "reservations": {},
    "shop_bays": {},
    "work_orders": {},
    "fuel_logs": {},
    "accident_claims": {},
    "disposals": {},
    "invoices": {},
}
clock = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}
_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def E_UNAUTH():
    return ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")


def E_FORBIDDEN(msg="Not permitted."):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def E_NOTFOUND(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def E_VALIDATION(msg="Invalid request body."):
    return ApiError("ERR_VALIDATION", 422, msg)


def E_PAGINATION():
    return ApiError("ERR_PAGINATION_INVALID", 400, "Invalid pagination parameters.")


def E_STATE(msg="Invalid state transition."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# =====================================================================
# Time / formatting helpers
# =====================================================================
def now_ts():
    return datetime.now(timezone.utc)


def iso_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        raise E_VALIDATION("Invalid datetime.")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        raise E_VALIDATION("Invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rand_id(n=20):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def rhu(x):
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =====================================================================
# Record creation / mutation
# =====================================================================
def base_record(versioned=True):
    now = now_ts()
    rec = {"id": str(uuid.uuid4()), "_seq": next_seq(), "created_at": now}
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    if "version" not in rec:
        return
    tset = getattr(g, "touched", None)
    if tset is None:
        tset = set()
        g.touched = tset
    if id(rec) in tset:
        return
    tset.add(id(rec))
    rec["version"] += 1
    rec["updated_at"] = now_ts()


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso_ms(v)
        else:
            out[k] = v
    return out


# =====================================================================
# Response envelope
# =====================================================================
def build_meta(extra=None):
    m = {
        "api_request_id": "req_" + rand_id(20),
        "api_request_timestamp": iso_ms(now_ts()),
    }
    if extra:
        m.update(extra)
    return m


def respond_object(data, code=200):
    return jsonify({"meta": build_meta(), "response_type": "object", "data": data}), code


def respond_array(items, limit, offset, total, code=200):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return jsonify({"meta": build_meta(pag), "response_type": "array", "data": items}), code


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# =====================================================================
# Auth
# =====================================================================
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise E_UNAUTH()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise E_FORBIDDEN("Role %s is not permitted for this operation." % role)


# =====================================================================
# Body / validation helpers
# =====================================================================
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise E_VALIDATION("Body must be a JSON object.")
    return b


def require_present(body, field):
    if field not in body or body[field] is None:
        raise E_VALIDATION("Missing required field: %s" % field)
    return body[field]


def as_int(v, field, allow_neg=False):
    if isinstance(v, bool):
        raise E_VALIDATION("Field %s must be an integer." % field)
    if isinstance(v, float):
        if not v.is_integer():
            raise E_VALIDATION("Field %s must be an integer." % field)
        v = int(v)
    if not isinstance(v, int):
        raise E_VALIDATION("Field %s must be an integer." % field)
    if not allow_neg and v < 0:
        raise E_VALIDATION("Field %s must be >= 0." % field)
    return v


def as_number(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise E_VALIDATION("Field %s must be a number." % field)
    return v


def req_int(body, field, allow_neg=False):
    return as_int(require_present(body, field), field, allow_neg)


def opt_int(body, field, default=0, allow_neg=False):
    if field not in body or body[field] is None:
        return default
    return as_int(body[field], field, allow_neg)


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise E_PAGINATION()
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise E_PAGINATION()
    if limit < 1 or limit > 100 or offset < 0:
        raise E_PAGINATION()
    return limit, offset


def list_response(records, reverse=False, extra_filter=None):
    limit, offset = parse_pagination()
    items = list(records)
    if extra_filter:
        items = [r for r in items if extra_filter(r)]
    items.sort(key=lambda r: r["_seq"], reverse=reverse)
    total = len(items)
    page = items[offset:offset + limit]
    return respond_array([serialize(r) for r in page], limit, offset, total)


# =====================================================================
# Lookup helpers
# =====================================================================
def get_or_404(store, rid):
    rec = db[store].get(rid)
    if rec is None:
        raise E_NOTFOUND("%s not found." % store)
    return rec


def policy_for(vehicle_class):
    for p in db["policies"].values():
        if p["vehicle_class"] == vehicle_class:
            return p
    return None


# =====================================================================
# Calculations
# =====================================================================
def compute_cost_per_mile(v):
    numerator = v["lifetime_maintenance_cents"] + v["lifetime_fuel_cents"]
    if v["odometer_miles"] == 0:
        return None
    return rhu(Decimal(numerator) / Decimal(v["odometer_miles"]))


def compute_replacement_score(v):
    p = policy_for(v["vehicle_class"])
    if p is None:
        return None
    isd = parse_dt(v["in_service_date"])
    age_secs = (clock["now"] - isd).total_seconds()
    age_years = Decimal(str(age_secs)) / Decimal("31536000")
    age_sub = min(Decimal(1), age_years / Decimal(p["replacement_age_years"]))
    if age_sub < 0:
        age_sub = Decimal(0)
    mile_sub = min(Decimal(1), Decimal(v["odometer_miles"]) / Decimal(p["replacement_mileage"]))
    acq = v["acquisition_cost_cents"]
    if acq <= 0:
        maint_sub = Decimal(1)
    else:
        maint_ratio = Decimal(v["lifetime_maintenance_cents"]) / Decimal(acq)
        maint_sub = min(Decimal(1), maint_ratio / Decimal(str(p["replacement_maint_ratio"])))
    score = Decimal(100) * (Decimal("0.30") * age_sub + Decimal("0.40") * mile_sub + Decimal("0.30") * maint_sub)
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def apply_replacement_score(v):
    score = compute_replacement_score(v)
    if score is None:
        return
    v["replacement_score"] = float(score)
    if score >= FLAG_THRESHOLD and v["lifecycle_status"] == "ACTIVE":
        v["lifecycle_status"] = "FLAGGED_FOR_REPLACEMENT"


def reservation_hold(res):
    s = parse_dt(res["requested_start"])
    e = parse_dt(res["requested_end"])
    secs = (e - s).total_seconds()
    hours = Decimal(str(secs)) / Decimal("3600")
    billable = int(hours.quantize(Decimal("1"), rounding=ROUND_CEILING))
    return billable * HOURLY_POOL_RATE_CENTS


def subrogation_gross(claim):
    return rhu(Decimal(claim["estimated_damage_cents"]) * Decimal(str(claim["third_party_liable_pct"])))


def subrogation_net(claim):
    gross = subrogation_gross(claim)
    return max(0, gross - claim["deductible_cents"] - SUBRO_ADMIN_FEE_CENTS)


def refresh_subrogation(claim):
    claim["gross_recoverable_cents"] = subrogation_gross(claim)
    claim["net_recoverable_cents"] = subrogation_net(claim)


def disposal_commission(sale_price):
    if sale_price <= 500000:
        rate = Decimal("0.10")
    elif sale_price <= 2000000:
        rate = Decimal("0.08")
    else:
        rate = Decimal("0.06")
    return rhu(Decimal(sale_price) * rate)


def select_pool_vehicle(res):
    ns = parse_dt(res["requested_start"])
    ne = parse_dt(res["requested_end"])
    cands = []
    for v in db["vehicles"].values():
        if v["assignment_type"] != "POOL":
            continue
        if v["operational_status"] != "IN_SERVICE":
            continue
        if v["lifecycle_status"] != "ACTIVE":
            continue
        conflict = False
        for r in db["reservations"].values():
            if r["assigned_vehicle_id"] == v["id"] and r["status"] in ("CONFIRMED", "CHECKED_OUT"):
                xs = parse_dt(r["requested_start"])
                xe = parse_dt(r["requested_end"])
                if xs < ne and ns < xe:
                    conflict = True
                    break
        if conflict:
            continue
        cands.append(v)
    cands.sort(key=lambda v: (v["odometer_miles"], v["_seq"]))
    return cands[0] if cands else None


def compute_chargeback(dept_id, ps_raw, pe_raw, basis):
    ps = parse_dt(ps_raw)
    pe = parse_dt(pe_raw)
    period_secs = (pe - ps).total_seconds()
    period_days = Decimal(str(period_secs)) / Decimal("86400")

    assigned = [
        v for v in db["vehicles"].values()
        if v["assignment_type"] == "DEPARTMENT_ASSIGNED" and v["assigned_department_id"] == dept_id
    ]

    # assignment fee (round per vehicle, then sum; not projected)
    assignment_fee = 0
    for v in assigned:
        p = policy_for(v["vehicle_class"])
        if p is None:
            continue
        isd = parse_dt(v["in_service_date"])
        active_from = isd if isd > ps else ps
        active_secs = (pe - active_from).total_seconds()
        active_days = Decimal(str(active_secs)) / Decimal("86400")
        if active_days < 0:
            active_days = Decimal(0)
        if period_days > 0:
            proration = active_days / period_days
            if proration > 1:
                proration = Decimal(1)
            if proration < 0:
                proration = Decimal(0)
        else:
            proration = Decimal(0)
        assignment_fee += rhu(Decimal(p["assignment_fee_cents_per_month"]) * proration)

    # mileage (exact integer per reservation)
    mileage_exact = 0
    for r in db["reservations"].values():
        if r["department_id"] != dept_id or r["status"] != "RETURNED":
            continue
        rs = parse_dt(r["requested_start"])
        if not (ps <= rs < pe):
            continue
        veh = db["vehicles"].get(r["assigned_vehicle_id"])
        if veh is None:
            continue
        p = policy_for(veh["vehicle_class"])
        if p is None:
            continue
        miles = r["miles_driven"] or 0
        b = p["mileage_tier_boundary_miles"]
        t1 = min(miles, b) * p["mileage_tier1_rate_cents"]
        t2 = max(0, miles - b) * p["mileage_tier2_rate_cents"]
        mileage_exact += t1 + t2

    # fuel surcharge
    fuel_final = 0
    fuel_preround = Decimal(0)
    for v in assigned:
        p = policy_for(v["vehicle_class"])
        if p is None:
            continue
        fsum = 0
        for fl in db["fuel_logs"].values():
            if fl["vehicle_id"] != v["id"]:
                continue
            if ps <= parse_dt(fl["reading_at"]) < pe:
                fsum += fl["fuel_cost_cents"]
        mult = Decimal(str(p["fuel_surcharge_multiplier"]))
        fuel_final += rhu(Decimal(fsum) * mult)
        fuel_preround += Decimal(fsum) * mult

    # idle penalty (exact integer per vehicle)
    idle_exact = 0
    for v in assigned:
        p = policy_for(v["vehicle_class"])
        if p is None:
            continue
        isum = 0
        for fl in db["fuel_logs"].values():
            if fl["vehicle_id"] != v["id"]:
                continue
            if ps <= parse_dt(fl["reading_at"]) < pe:
                isum += fl.get("idle_minutes", 0) or 0
        excess = isum - p["idle_free_minutes"]
        if excess < 0:
            excess = 0
        idle_exact += excess * p["idle_penalty_cents_per_min"]

    if basis == "PROVISIONAL":
        elapsed_secs = (clock["now"] - ps).total_seconds()
        elapsed_days = math.floor(elapsed_secs / 86400)
        if elapsed_days < 1:
            elapsed_days = 1
        pf = period_days / Decimal(elapsed_days)
        mileage = rhu(Decimal(mileage_exact) * pf)
        fuel = rhu(fuel_preround * pf)
        idle = rhu(Decimal(idle_exact) * pf)
    else:
        mileage = mileage_exact
        fuel = fuel_final
        idle = idle_exact

    total = assignment_fee + mileage + fuel + idle
    return {
        "assignment_fee_cents": assignment_fee,
        "mileage_charge_cents": mileage,
        "fuel_surcharge_cents": fuel,
        "idle_penalty_cents": idle,
        "total_cents": total,
    }


# =====================================================================
# Clock endpoint (auth-exempt)
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    clock["now"] = parse_dt(to_iso)
    return respond_object({"current_utc": to_iso}, 200)


# =====================================================================
# Vehicles
# =====================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    body = get_body()
    vin = require_present(body, "vin")
    vehicle_class = require_present(body, "vehicle_class")
    acq = req_int(body, "acquisition_cost_cents")
    in_service = require_present(body, "in_service_date")
    if not isinstance(vin, str) or not (1 <= len(vin) <= 64):
        raise E_VALIDATION("vin must be 1..64 chars.")
    if vehicle_class not in VEHICLE_CLASSES:
        raise E_VALIDATION("Invalid vehicle_class.")
    parse_dt(in_service)
    for v in db["vehicles"].values():
        if v["vin"] == vin:
            raise ApiError("ERR_DUPLICATE", 409, "vin already exists.")
    rec = base_record()
    rec.update({
        "vin": vin,
        "vehicle_class": vehicle_class,
        "acquisition_cost_cents": acq,
        "in_service_date": in_service,
        "odometer_miles": 0,
        "assignment_type": "POOL",
        "assigned_department_id": None,
        "operational_status": "IN_SERVICE",
        "lifecycle_status": "ACTIVE",
        "lifetime_maintenance_cents": 0,
        "replacement_score": 0,
        "open_accident_count": 0,
        "lifetime_fuel_cents": 0,
        "cost_per_mile_cents": None,
    })
    db["vehicles"][rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "MotorPoolClerk", "ShopTech", "FinanceOfficer"})
    filters = {}
    for f in ("operational_status", "lifecycle_status", "assignment_type", "vehicle_class"):
        if request.args.get(f) is not None:
            filters[f] = request.args.get(f)

    def match(v):
        return all(v.get(k) == val for k, val in filters.items())

    return list_response(db["vehicles"].values(), extra_filter=match)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "MotorPoolClerk", "ShopTech", "FinanceOfficer"})
    return respond_object(serialize(get_or_404("vehicles", vid)))


@app.route("/vehicles/<vid>/assignment", methods=["PATCH"])
def assign_vehicle(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    v = get_or_404("vehicles", vid)
    body = get_body()
    atype = require_present(body, "assignment_type")
    if atype not in ASSIGNMENT_TYPES:
        raise E_VALIDATION("Invalid assignment_type.")
    dept_id = body.get("assigned_department_id")
    if dept_id is not None:
        get_or_404("departments", dept_id)
    if atype == "DEPARTMENT_ASSIGNED":
        if not dept_id:
            raise ApiError("ERR_ASSIGNMENT_INVALID", 409, "DEPARTMENT_ASSIGNED requires assigned_department_id.")
        v["assignment_type"] = "DEPARTMENT_ASSIGNED"
        v["assigned_department_id"] = dept_id
    else:
        if dept_id:
            raise ApiError("ERR_ASSIGNMENT_INVALID", 409, "POOL vehicle cannot carry assigned_department_id.")
        v["assignment_type"] = "POOL"
        v["assigned_department_id"] = None
    touch(v)
    return respond_object(serialize(v))


@app.route("/vehicles/<vid>/replacement-evaluation", methods=["POST"])
def eval_replacement(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    v = get_or_404("vehicles", vid)
    apply_replacement_score(v)
    touch(v)
    return respond_object(serialize(v))


@app.route("/vehicles/<vid>/fuel-logs", methods=["POST"])
def create_fuel_log(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    v = get_or_404("vehicles", vid)
    body = get_body()
    reading_at = require_present(body, "reading_at")
    gallons = as_number(require_present(body, "gallons"), "gallons")
    fuel_cost = req_int(body, "fuel_cost_cents")
    odo = req_int(body, "odometer_miles")
    idle = opt_int(body, "idle_minutes", 0)
    engine_hours = body.get("engine_hours", 0)
    if engine_hours is None:
        engine_hours = 0
    else:
        engine_hours = as_number(engine_hours, "engine_hours")
    if gallons < 0:
        raise E_VALIDATION("gallons must be >= 0.")
    parse_dt(reading_at)
    rec = base_record(versioned=False)
    rec.update({
        "vehicle_id": vid,
        "reading_at": reading_at,
        "gallons": gallons,
        "fuel_cost_cents": fuel_cost,
        "odometer_miles": odo,
        "idle_minutes": idle,
        "engine_hours": engine_hours,
    })
    db["fuel_logs"][rec["id"]] = rec
    if odo > v["odometer_miles"]:
        v["odometer_miles"] = odo
    v["lifetime_fuel_cents"] += fuel_cost
    v["cost_per_mile_cents"] = compute_cost_per_mile(v)
    touch(v)
    return respond_object(serialize(rec), 201)


@app.route("/vehicles/<vid>/fuel-logs", methods=["GET"])
def list_fuel_logs(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech", "FinanceOfficer"})
    get_or_404("vehicles", vid)
    return list_response(db["fuel_logs"].values(), reverse=True,
                         extra_filter=lambda f: f["vehicle_id"] == vid)


@app.route("/vehicles/<vid>/disposals", methods=["GET"])
def list_vehicle_disposals(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    get_or_404("vehicles", vid)
    return list_response(db["disposals"].values(), reverse=True,
                         extra_filter=lambda d: d["vehicle_id"] == vid)


@app.route("/vehicles/<vid>/disposals", methods=["POST"])
def create_disposal(vid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    v = get_or_404("vehicles", vid)
    body = get_body()
    reserve = req_int(body, "reserve_price_cents")
    recond = opt_int(body, "reconditioning_cost_cents", 0)
    expected = as_int(require_present(body, "expected_vehicle_version"), "expected_vehicle_version", allow_neg=True)
    # OCC (tier 5)
    if expected != v["version"]:
        raise ApiError("ERR_STALE_VEHICLE_VERSION", 412, "Stale vehicle version.")
    # state (tier 6)
    if v["lifecycle_status"] != "FLAGGED_FOR_REPLACEMENT":
        raise E_STATE("Vehicle must be FLAGGED_FOR_REPLACEMENT to list for disposal.")
    # business safety (tier 7)
    if v["open_accident_count"] > 0 or v["operational_status"] == "IN_SHOP":
        raise ApiError("ERR_DISPOSAL_BLOCKED", 409, "Vehicle cannot be listed while it has open accidents or is in shop.")
    rec = base_record()
    rec.update({
        "vehicle_id": vid,
        "reserve_price_cents": reserve,
        "reconditioning_cost_cents": recond,
        "status": "LISTED",
        "sale_price_cents": None,
        "commission_cents": None,
        "net_proceeds_cents": None,
        "buyer_name": None,
    })
    db["disposals"][rec["id"]] = rec
    v["lifecycle_status"] = "PENDING_DISPOSAL"
    touch(v)
    return respond_object(serialize(rec), 201)


# =====================================================================
# Departments
# =====================================================================
@app.route("/departments", methods=["POST"])
def create_department():
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    body = get_body()
    name = require_present(body, "name")
    cost_center = require_present(body, "cost_center_code")
    budget = req_int(body, "monthly_budget_cents")
    for d in db["departments"].values():
        if d["cost_center_code"] == cost_center:
            raise ApiError("ERR_DUPLICATE", 409, "cost_center_code already exists.")
    rec = base_record()
    rec.update({
        "name": name,
        "cost_center_code": cost_center,
        "monthly_budget_cents": budget,
        "committed_budget_cents": 0,
        "billed_ytd_cents": 0,
    })
    db["departments"][rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@app.route("/departments/<did>", methods=["GET"])
def get_department(did):
    uid, role = require_auth()
    require_role(role, {"FleetAdmin", "FinanceOfficer", "DepartmentUser"})
    if role == "DepartmentUser" and did != uid:
        raise E_FORBIDDEN("DepartmentUser may only access its own department.")
    return respond_object(serialize(get_or_404("departments", did)))


@app.route("/departments/<did>/vehicles", methods=["GET"])
def list_department_vehicles(did):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "FinanceOfficer"})
    get_or_404("departments", did)
    return list_response(db["vehicles"].values(),
                         extra_filter=lambda v: v["assigned_department_id"] == did)


@app.route("/departments/<did>/chargeback-invoices", methods=["GET"])
def list_department_invoices(did):
    uid, role = require_auth()
    require_role(role, {"FleetAdmin", "FinanceOfficer", "DepartmentUser"})
    if role == "DepartmentUser" and did != uid:
        raise E_FORBIDDEN("DepartmentUser may only access its own department.")
    get_or_404("departments", did)
    status = request.args.get("status")

    def match(inv):
        if inv["department_id"] != did:
            return False
        if status is not None and inv["status"] != status:
            return False
        return True

    return list_response(db["invoices"].values(), extra_filter=match)


@app.route("/departments/<did>/chargeback-invoices", methods=["POST"])
def create_invoice(did):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    dept = get_or_404("departments", did)
    body = get_body()
    ps = require_present(body, "period_start")
    pe = require_present(body, "period_end")
    basis = body.get("basis", "FINAL")
    if basis is None:
        basis = "FINAL"
    if basis not in BASIS_TYPES:
        raise E_VALIDATION("Invalid basis.")
    parse_dt(ps)
    parse_dt(pe)
    expected = as_int(require_present(body, "expected_department_version"), "expected_department_version", allow_neg=True)
    if expected != dept["version"]:
        raise ApiError("ERR_STALE_DEPARTMENT_VERSION", 412, "Stale department version.")
    lines = compute_chargeback(did, ps, pe, basis)
    rec = base_record()
    rec.update({
        "department_id": did,
        "period_start": ps,
        "period_end": pe,
        "basis": basis,
        "status": "DRAFT",
        "disputed_reason": None,
    })
    rec.update(lines)
    db["invoices"][rec["id"]] = rec
    touch(dept)
    return respond_object(serialize(rec), 201)


# =====================================================================
# Vehicle Class Policies
# =====================================================================
@app.route("/vehicle-class-policies", methods=["POST"])
def create_policy():
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    body = get_body()
    vc = require_present(body, "vehicle_class")
    if vc not in VEHICLE_CLASSES:
        raise E_VALIDATION("Invalid vehicle_class.")
    assign_fee = req_int(body, "assignment_fee_cents_per_month")
    t1 = req_int(body, "mileage_tier1_rate_cents")
    t2 = req_int(body, "mileage_tier2_rate_cents")
    boundary = req_int(body, "mileage_tier_boundary_miles")
    fuel_mult = as_number(require_present(body, "fuel_surcharge_multiplier"), "fuel_surcharge_multiplier")
    idle_free = req_int(body, "idle_free_minutes")
    idle_pen = req_int(body, "idle_penalty_cents_per_min")
    rep_age = req_int(body, "replacement_age_years")
    rep_mileage = req_int(body, "replacement_mileage")
    rep_maint = as_number(require_present(body, "replacement_maint_ratio"), "replacement_maint_ratio")
    if fuel_mult < 0:
        raise E_VALIDATION("fuel_surcharge_multiplier must be >= 0.")
    if rep_age < 1:
        raise E_VALIDATION("replacement_age_years must be >= 1.")
    if rep_mileage < 1:
        raise E_VALIDATION("replacement_mileage must be >= 1.")
    if rep_maint <= 0:
        raise E_VALIDATION("replacement_maint_ratio must be > 0.")
    if policy_for(vc) is not None:
        raise ApiError("ERR_DUPLICATE", 409, "policy for vehicle_class already exists.")
    rec = base_record(versioned=False)
    rec.update({
        "vehicle_class": vc,
        "assignment_fee_cents_per_month": assign_fee,
        "mileage_tier1_rate_cents": t1,
        "mileage_tier2_rate_cents": t2,
        "mileage_tier_boundary_miles": boundary,
        "fuel_surcharge_multiplier": fuel_mult,
        "idle_free_minutes": idle_free,
        "idle_penalty_cents_per_min": idle_pen,
        "replacement_age_years": rep_age,
        "replacement_mileage": rep_mileage,
        "replacement_maint_ratio": rep_maint,
    })
    db["policies"][rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@app.route("/vehicle-class-policies/<pid>", methods=["GET"])
def get_policy(pid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "FinanceOfficer"})
    return respond_object(serialize(get_or_404("policies", pid)))


# =====================================================================
# Reservations
# =====================================================================
@app.route("/reservations", methods=["POST"])
def create_reservation():
    uid, role = require_auth()
    require_role(role, {"MotorPoolClerk", "DepartmentUser"})
    body = get_body()
    dept_id = body.get("department_id")
    if role == "DepartmentUser" and dept_id is not None and dept_id != uid:
        raise E_FORBIDDEN("DepartmentUser may only reserve for its own department.")
    if dept_id is not None:
        get_or_404("departments", dept_id)
    require_present(body, "department_id")
    rs = require_present(body, "requested_start")
    re = require_present(body, "requested_end")
    driver = require_present(body, "driver_name")
    purpose = require_present(body, "purpose")
    sdt = parse_dt(rs)
    edt = parse_dt(re)
    if edt <= sdt:
        raise E_VALIDATION("requested_end must be strictly after requested_start.")
    rec = base_record()
    rec.update({
        "department_id": dept_id,
        "requested_start": rs,
        "requested_end": re,
        "driver_name": driver,
        "purpose": purpose,
        "assigned_vehicle_id": None,
        "status": "REQUESTED",
        "estimated_cost_cents": 0,
        "checkout_odometer": None,
        "return_odometer": None,
        "miles_driven": None,
    })
    db["reservations"][rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@app.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    uid, role = require_auth()
    require_role(role, {"MotorPoolClerk", "DepartmentUser", "FleetAdmin"})
    res = get_or_404("reservations", rid)
    if role == "DepartmentUser" and res["department_id"] != uid:
        raise E_FORBIDDEN("DepartmentUser may only access its own reservations.")
    return respond_object(serialize(res))


@app.route("/reservations", methods=["GET"])
def list_reservations():
    _, role = require_auth()
    require_role(role, {"MotorPoolClerk", "FleetAdmin"})
    filters = {}
    for f in ("department_id", "assigned_vehicle_id", "status"):
        if request.args.get(f) is not None:
            filters[f] = request.args.get(f)

    def match(r):
        return all(r.get(k) == val for k, val in filters.items())

    return list_response(db["reservations"].values(), extra_filter=match)


@app.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    _, role = require_auth()
    require_role(role, {"MotorPoolClerk"})
    res = get_or_404("reservations", rid)
    if res["status"] != "REQUESTED":
        raise E_STATE("Reservation must be REQUESTED to confirm.")
    est = reservation_hold(res)
    veh = select_pool_vehicle(res)
    if veh is None:
        raise ApiError("ERR_NO_VEHICLE_AVAILABLE", 409, "No POOL vehicle available for the window.")
    dept = db["departments"].get(res["department_id"])
    if dept is None:
        raise E_NOTFOUND("Department not found.")
    if dept["committed_budget_cents"] + est > dept["monthly_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 409, "Budget ceiling exceeded.")
    res["assigned_vehicle_id"] = veh["id"]
    res["estimated_cost_cents"] = est
    res["status"] = "CONFIRMED"
    touch(res)
    dept["committed_budget_cents"] += est
    touch(dept)
    return respond_object(serialize(res))


@app.route("/reservations/<rid>/checkout", methods=["POST"])
def checkout_reservation(rid):
    _, role = require_auth()
    require_role(role, {"MotorPoolClerk"})
    res = get_or_404("reservations", rid)
    body = get_body()
    co = req_int(body, "checkout_odometer")
    if res["status"] != "CONFIRMED":
        raise E_STATE("Reservation must be CONFIRMED to checkout.")
    veh = db["vehicles"].get(res["assigned_vehicle_id"])
    if veh is None or veh["operational_status"] != "IN_SERVICE":
        raise E_STATE("Assigned vehicle is not IN_SERVICE.")
    if co < veh["odometer_miles"]:
        raise ApiError("ERR_ODOMETER_ROLLBACK", 409, "checkout_odometer below vehicle odometer.")
    res["checkout_odometer"] = co
    res["status"] = "CHECKED_OUT"
    touch(res)
    return respond_object(serialize(res))


@app.route("/reservations/<rid>/return", methods=["POST"])
def return_reservation(rid):
    _, role = require_auth()
    require_role(role, {"MotorPoolClerk"})
    res = get_or_404("reservations", rid)
    body = get_body()
    ro = req_int(body, "return_odometer")
    if res["status"] != "CHECKED_OUT":
        raise E_STATE("Reservation must be CHECKED_OUT to return.")
    if ro < res["checkout_odometer"]:
        raise ApiError("ERR_ODOMETER_ROLLBACK", 409, "return_odometer below checkout_odometer.")
    res["return_odometer"] = ro
    res["miles_driven"] = ro - res["checkout_odometer"]
    res["status"] = "RETURNED"
    touch(res)
    veh = db["vehicles"].get(res["assigned_vehicle_id"])
    if veh is not None:
        if ro > veh["odometer_miles"]:
            veh["odometer_miles"] = ro
            veh["cost_per_mile_cents"] = compute_cost_per_mile(veh)
        touch(veh)
    dept = db["departments"].get(res["department_id"])
    if dept is not None:
        dept["committed_budget_cents"] -= res["estimated_cost_cents"]
        touch(dept)
    return respond_object(serialize(res))


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, role = require_auth()
    require_role(role, {"MotorPoolClerk", "DepartmentUser"})
    res = get_or_404("reservations", rid)
    if role == "DepartmentUser" and res["department_id"] != uid:
        raise E_FORBIDDEN("DepartmentUser may only cancel its own reservations.")
    if res["status"] not in ("REQUESTED", "CONFIRMED"):
        raise E_STATE("Reservation can only be cancelled from REQUESTED or CONFIRMED.")
    was_confirmed = res["status"] == "CONFIRMED"
    res["status"] = "CANCELLED"
    touch(res)
    if was_confirmed:
        dept = db["departments"].get(res["department_id"])
        if dept is not None:
            dept["committed_budget_cents"] -= res["estimated_cost_cents"]
            touch(dept)
    return respond_object(serialize(res))


# =====================================================================
# Shop Bays
# =====================================================================
@app.route("/shop-bays", methods=["POST"])
def create_shop_bay():
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    body = get_body()
    name = require_present(body, "name")
    bay_type = require_present(body, "bay_type")
    if bay_type not in BAY_TYPES:
        raise E_VALIDATION("Invalid bay_type.")
    for b in db["shop_bays"].values():
        if b["name"] == name:
            raise ApiError("ERR_DUPLICATE", 409, "bay name already exists.")
    rec = base_record()
    rec.update({"name": name, "bay_type": bay_type, "status": "AVAILABLE"})
    db["shop_bays"][rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@app.route("/shop-bays/<bid>", methods=["GET"])
def get_shop_bay(bid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    return respond_object(serialize(get_or_404("shop_bays", bid)))


@app.route("/shop-bays/<bid>", methods=["PATCH"])
def patch_shop_bay(bid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    bay = get_or_404("shop_bays", bid)
    body = get_body()
    status = require_present(body, "status")
    if status not in ("AVAILABLE", "CLOSED"):
        raise E_VALIDATION("Invalid status.")
    bay["status"] = status
    touch(bay)
    return respond_object(serialize(bay))


@app.route("/shop-bays/<bid>/work-orders", methods=["GET"])
def list_bay_work_orders(bid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    get_or_404("shop_bays", bid)
    return list_response(db["work_orders"].values(),
                         extra_filter=lambda w: w["bay_id"] == bid)


# =====================================================================
# Work Orders
# =====================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    _, role = require_auth()
    require_role(role, {"ShopTech"})
    body = get_body()
    vehicle_id = body.get("vehicle_id")
    bay_id = body.get("bay_id")
    if vehicle_id is not None and vehicle_id not in db["vehicles"]:
        raise E_NOTFOUND("vehicle not found.")
    if bay_id is not None and bay_id not in db["shop_bays"]:
        raise E_NOTFOUND("bay not found.")
    require_present(body, "vehicle_id")
    require_present(body, "bay_id")
    wo_type = require_present(body, "wo_type")
    ss = require_present(body, "scheduled_start")
    se = require_present(body, "scheduled_end")
    labor_rate = req_int(body, "labor_rate_cents")
    if wo_type not in WO_TYPES:
        raise E_VALIDATION("Invalid wo_type.")
    sdt = parse_dt(ss)
    edt = parse_dt(se)
    if edt <= sdt:
        raise E_VALIDATION("scheduled_end must be strictly after scheduled_start.")
    veh = db["vehicles"][vehicle_id]
    # tier 6: disposed
    if veh["lifecycle_status"] == "DISPOSED":
        raise ApiError("ERR_VEHICLE_DISPOSED", 409, "Vehicle is disposed.")
    # tier 7: open accident blocks PM
    if wo_type == "PM" and veh["open_accident_count"] > 0:
        raise ApiError("ERR_OPEN_ACCIDENT_BLOCKS_WO", 409, "Open accident blocks PM work order.")
    # tier 8: bay time conflict
    for w in db["work_orders"].values():
        if w["bay_id"] != bay_id or w["status"] not in WO_ACTIVE:
            continue
        es = parse_dt(w["scheduled_start"])
        ee = parse_dt(w["scheduled_end"])
        if sdt < ee + BAY_BUFFER and es < edt + BAY_BUFFER:
            raise ApiError("ERR_BAY_TIME_CONFLICT", 409, "Bay time conflict.")
    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "bay_id": bay_id,
        "wo_type": wo_type,
        "scheduled_start": ss,
        "scheduled_end": se,
        "status": "SCHEDULED",
        "labor_hours": None,
        "labor_rate_cents": labor_rate,
        "parts_cost_cents": 0,
        "total_cost_cents": None,
    })
    db["work_orders"][rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@app.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    return respond_object(serialize(get_or_404("work_orders", wid)))


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    _, role = require_auth()
    require_role(role, {"FleetAdmin", "ShopTech"})
    filters = {}
    for f in ("vehicle_id", "bay_id", "status"):
        if request.args.get(f) is not None:
            filters[f] = request.args.get(f)

    def match(w):
        return all(w.get(k) == val for k, val in filters.items())

    return list_response(db["work_orders"].values(), extra_filter=match)


@app.route("/work-orders/<wid>/start", methods=["POST"])
def start_work_order(wid):
    _, role = require_auth()
    require_role(role, {"ShopTech"})
    wo = get_or_404("work_orders", wid)
    veh = db["vehicles"].get(wo["vehicle_id"])
    if wo["status"] == "AWAITING_PARTS":
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        return respond_object(serialize(wo))
    if wo["status"] != "SCHEDULED":
        raise E_STATE("Work order cannot be started from its current state.")
    if veh is not None and veh["lifecycle_status"] == "DISPOSED":
        raise ApiError("ERR_VEHICLE_DISPOSED", 409, "Vehicle is disposed.")
    bay = db["shop_bays"].get(wo["bay_id"])
    if bay is not None and bay["status"] != "AVAILABLE":
        raise ApiError("ERR_BAY_CLOSED", 409, "Bay is closed.")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    if veh is not None:
        veh["operational_status"] = "IN_SHOP"
        touch(veh)
    return respond_object(serialize(wo))


@app.route("/work-orders/<wid>/hold-parts", methods=["POST"])
def hold_parts_work_order(wid):
    _, role = require_auth()
    require_role(role, {"ShopTech"})
    wo = get_or_404("work_orders", wid)
    if wo["status"] != "IN_PROGRESS":
        raise E_STATE("Work order must be IN_PROGRESS to hold for parts.")
    wo["status"] = "AWAITING_PARTS"
    touch(wo)
    return respond_object(serialize(wo))


@app.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    _, role = require_auth()
    require_role(role, {"ShopTech"})
    wo = get_or_404("work_orders", wid)
    body = get_body()
    labor_hours = require_present(body, "labor_hours")
    labor_hours = as_number(labor_hours, "labor_hours")
    if labor_hours < 0:
        raise E_VALIDATION("labor_hours must be >= 0.")
    parts_cost = opt_int(body, "parts_cost_cents", 0)
    if wo["status"] not in ("IN_PROGRESS",):
        raise E_STATE("Work order must be IN_PROGRESS to complete.")
    total = rhu(Decimal(str(labor_hours)) * Decimal(wo["labor_rate_cents"])) + parts_cost
    wo["labor_hours"] = labor_hours
    wo["parts_cost_cents"] = parts_cost
    wo["total_cost_cents"] = total
    wo["status"] = "COMPLETED"
    touch(wo)
    veh = db["vehicles"].get(wo["vehicle_id"])
    if veh is not None:
        veh["operational_status"] = "IN_SERVICE"
        veh["lifetime_maintenance_cents"] += total
        veh["cost_per_mile_cents"] = compute_cost_per_mile(veh)
        apply_replacement_score(veh)
        touch(veh)
    return respond_object(serialize(wo))


@app.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel_work_order(wid):
    _, role = require_auth()
    require_role(role, {"ShopTech"})
    wo = get_or_404("work_orders", wid)
    if wo["status"] != "SCHEDULED":
        raise E_STATE("Work order can only be cancelled from SCHEDULED.")
    wo["status"] = "CANCELLED"
    touch(wo)
    return respond_object(serialize(wo))


# =====================================================================
# Accident Claims
# =====================================================================
@app.route("/accident-claims", methods=["POST"])
def create_accident_claim():
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    body = get_body()
    vehicle_id = body.get("vehicle_id")
    if vehicle_id is not None and vehicle_id not in db["vehicles"]:
        raise E_NOTFOUND("vehicle not found.")
    require_present(body, "vehicle_id")
    reported_at = require_present(body, "reported_at")
    if "at_fault" not in body or body["at_fault"] is None:
        raise E_VALIDATION("Missing required field: at_fault")
    at_fault = body["at_fault"]
    if not isinstance(at_fault, bool):
        raise E_VALIDATION("at_fault must be boolean.")
    damage = req_int(body, "estimated_damage_cents")
    deductible = opt_int(body, "deductible_cents", 0)
    pct = body.get("third_party_liable_pct", 0)
    if pct is None:
        pct = 0
    pct = as_number(pct, "third_party_liable_pct")
    if pct < 0 or pct > 1:
        raise E_VALIDATION("third_party_liable_pct must be in [0,1].")
    if at_fault and pct > 0:
        raise E_VALIDATION("third_party_liable_pct must be 0 when at_fault is true.")
    parse_dt(reported_at)
    veh = db["vehicles"][vehicle_id]
    if veh["lifecycle_status"] == "DISPOSED":
        raise ApiError("ERR_VEHICLE_DISPOSED", 409, "Vehicle is disposed.")
    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "reported_at": reported_at,
        "at_fault": at_fault,
        "estimated_damage_cents": damage,
        "deductible_cents": deductible,
        "third_party_liable_pct": pct,
        "status": "REPORTED",
        "recovered_cents": 0,
        "outstanding_liable_cents": 0,
        "gross_recoverable_cents": 0,
        "net_recoverable_cents": 0,
    })
    refresh_subrogation(rec)
    db["accident_claims"][rec["id"]] = rec
    veh["open_accident_count"] += 1
    if at_fault or damage >= 500000:
        veh["operational_status"] = "OUT_OF_SERVICE"
        for r in db["reservations"].values():
            if (r["assigned_vehicle_id"] == vehicle_id and r["status"] == "CONFIRMED"
                    and parse_dt(r["requested_start"]) > clock["now"]):
                r["status"] = "CANCELLED"
                touch(r)
                dept = db["departments"].get(r["department_id"])
                if dept is not None:
                    dept["committed_budget_cents"] -= r["estimated_cost_cents"]
                    touch(dept)
    touch(veh)
    return respond_object(serialize(rec), 201)


@app.route("/accident-claims/<cid>", methods=["GET"])
def get_accident_claim(cid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer", "FleetAdmin"})
    return respond_object(serialize(get_or_404("accident_claims", cid)))


@app.route("/accident-claims", methods=["GET"])
def list_accident_claims():
    _, role = require_auth()
    require_role(role, {"FinanceOfficer", "FleetAdmin"})
    filters = {}
    for f in ("vehicle_id", "status"):
        if request.args.get(f) is not None:
            filters[f] = request.args.get(f)

    def match(c):
        return all(c.get(k) == val for k, val in filters.items())

    return list_response(db["accident_claims"].values(), extra_filter=match)


@app.route("/accident-claims/<cid>/investigate", methods=["POST"])
def investigate_claim(cid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    claim = get_or_404("accident_claims", cid)
    if claim["status"] != "REPORTED":
        raise E_STATE("Claim must be REPORTED to investigate.")
    claim["status"] = "UNDER_INVESTIGATION"
    touch(claim)
    return respond_object(serialize(claim))


@app.route("/accident-claims/<cid>/subrogate", methods=["POST"])
def subrogate_claim(cid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    claim = get_or_404("accident_claims", cid)
    if claim["status"] != "UNDER_INVESTIGATION":
        raise E_STATE("Claim must be UNDER_INVESTIGATION to subrogate.")
    if claim["at_fault"] or claim["third_party_liable_pct"] <= 0:
        raise ApiError("ERR_SUBROGATION_INVALID", 409, "Subrogation requires not-at-fault and positive liability.")
    claim["status"] = "SUBROGATION_PENDING"
    refresh_subrogation(claim)
    claim["outstanding_liable_cents"] = claim["gross_recoverable_cents"] - claim["recovered_cents"]
    touch(claim)
    return respond_object(serialize(claim))


@app.route("/accident-claims/<cid>/record-recovery", methods=["POST"])
def record_recovery(cid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    claim = get_or_404("accident_claims", cid)
    body = get_body()
    amount = req_int(body, "amount_cents")
    if claim["status"] != "SUBROGATION_PENDING":
        raise E_STATE("Claim must be SUBROGATION_PENDING to record a recovery.")
    gross = claim["gross_recoverable_cents"]
    if amount <= 0 or claim["recovered_cents"] + amount > gross:
        raise ApiError("ERR_SUBROGATION_INVALID", 409, "Invalid recovery amount.")
    claim["recovered_cents"] += amount
    claim["outstanding_liable_cents"] = gross - claim["recovered_cents"]
    touch(claim)
    return respond_object(serialize(claim))


@app.route("/accident-claims/<cid>/dispute", methods=["POST"])
def dispute_claim(cid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    claim = get_or_404("accident_claims", cid)
    body = get_body()
    reversal = req_int(body, "reversal_cents")
    if claim["status"] != "SUBROGATION_PENDING":
        raise E_STATE("Claim must be SUBROGATION_PENDING to dispute.")
    if reversal <= 0 or reversal > claim["recovered_cents"]:
        raise ApiError("ERR_SUBROGATION_INVALID", 409, "Invalid reversal amount.")
    claim["recovered_cents"] -= reversal
    claim["outstanding_liable_cents"] = claim["gross_recoverable_cents"] - claim["recovered_cents"]
    claim["status"] = "UNDER_INVESTIGATION"
    touch(claim)
    return respond_object(serialize(claim))


@app.route("/accident-claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    claim = get_or_404("accident_claims", cid)
    body = get_body()
    disposition = require_present(body, "disposition")
    if disposition not in DISPOSITIONS:
        raise E_VALIDATION("Invalid disposition.")
    veh = db["vehicles"].get(claim["vehicle_id"])
    if disposition == "RECOVERED":
        if claim["status"] != "SUBROGATION_PENDING":
            raise E_STATE("RECOVERED close requires SUBROGATION_PENDING.")
        if claim["outstanding_liable_cents"] != 0:
            raise E_STATE("RECOVERED close requires outstanding_liable_cents == 0.")
        claim["status"] = "RECOVERED"
    elif disposition == "WRITE_OFF":
        if claim["status"] != "UNDER_INVESTIGATION" or not claim["at_fault"]:
            raise E_STATE("WRITE_OFF close requires UNDER_INVESTIGATION and at_fault.")
        claim["status"] = "WRITTEN_OFF"
    else:  # RETURN_TO_SERVICE
        if claim["status"] not in ("UNDER_INVESTIGATION", "SUBROGATION_PENDING") or claim["at_fault"]:
            raise E_STATE("RETURN_TO_SERVICE close requires not-at-fault UNDER_INVESTIGATION/SUBROGATION_PENDING.")
        claim["status"] = "CLOSED_NO_FAULT"
        if veh is not None and veh["operational_status"] == "OUT_OF_SERVICE":
            has_open_wo = any(
                w["vehicle_id"] == veh["id"] and w["status"] in WO_ACTIVE
                for w in db["work_orders"].values()
            )
            if not has_open_wo:
                veh["operational_status"] = "IN_SERVICE"
                touch(veh)
    # terminal reached -> decrement open accident count
    if veh is not None:
        veh["open_accident_count"] = max(0, veh["open_accident_count"] - 1)
        touch(veh)
    touch(claim)
    return respond_object(serialize(claim))


# =====================================================================
# Disposals
# =====================================================================
@app.route("/disposals/<did>", methods=["GET"])
def get_disposal(did):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    return respond_object(serialize(get_or_404("disposals", did)))


@app.route("/disposals/<did>/open-bidding", methods=["POST"])
def open_bidding(did):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    disp = get_or_404("disposals", did)
    veh = db["vehicles"].get(disp["vehicle_id"])
    if disp["status"] == "LISTED":
        if veh is None or veh["lifecycle_status"] != "PENDING_DISPOSAL":
            raise E_STATE("Vehicle must be PENDING_DISPOSAL.")
        disp["status"] = "BIDDING"
    elif disp["status"] == "NO_SALE":
        if veh is None or veh["lifecycle_status"] != "PENDING_DISPOSAL":
            raise E_STATE("Vehicle must be PENDING_DISPOSAL to relist.")
        disp["status"] = "LISTED"
    else:
        raise E_STATE("Disposal cannot open bidding from its current state.")
    touch(disp)
    return respond_object(serialize(disp))


@app.route("/disposals/<did>/sell", methods=["POST"])
def sell_disposal(did):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    disp = get_or_404("disposals", did)
    body = get_body()
    sale_price = req_int(body, "sale_price_cents")
    buyer = require_present(body, "buyer_name")
    if disp["status"] != "BIDDING":
        raise E_STATE("Disposal must be BIDDING to sell.")
    if sale_price < disp["reserve_price_cents"]:
        raise ApiError("ERR_BELOW_RESERVE", 409, "Sale price below reserve.")
    commission = disposal_commission(sale_price)
    net = sale_price - commission - disp["reconditioning_cost_cents"]
    disp["sale_price_cents"] = sale_price
    disp["buyer_name"] = buyer
    disp["commission_cents"] = commission
    disp["net_proceeds_cents"] = net
    disp["status"] = "SOLD"
    touch(disp)
    veh = db["vehicles"].get(disp["vehicle_id"])
    if veh is not None:
        veh["lifecycle_status"] = "DISPOSED"
        veh["operational_status"] = "OUT_OF_SERVICE"
        touch(veh)
        if veh["assigned_department_id"] is not None:
            dept = db["departments"].get(veh["assigned_department_id"])
            if dept is not None:
                dept["billed_ytd_cents"] -= net
                touch(dept)
    return respond_object(serialize(disp))


@app.route("/disposals/<did>/no-sale", methods=["POST"])
def no_sale_disposal(did):
    _, role = require_auth()
    require_role(role, {"FleetAdmin"})
    disp = get_or_404("disposals", did)
    if disp["status"] != "BIDDING":
        raise E_STATE("Disposal must be BIDDING to mark no-sale.")
    disp["status"] = "NO_SALE"
    touch(disp)
    return respond_object(serialize(disp))


# =====================================================================
# Chargeback Invoices
# =====================================================================
@app.route("/chargeback-invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = require_auth()
    require_role(role, {"FinanceOfficer", "DepartmentUser", "FleetAdmin"})
    inv = get_or_404("invoices", iid)
    if role == "DepartmentUser" and inv["department_id"] != uid:
        raise E_FORBIDDEN("DepartmentUser may only access its own invoices.")
    return respond_object(serialize(inv))


@app.route("/chargeback-invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise E_STATE("Invoice must be DRAFT to issue.")
    lines = compute_chargeback(inv["department_id"], inv["period_start"], inv["period_end"], inv["basis"])
    inv.update(lines)
    inv["status"] = "ISSUED"
    touch(inv)
    dept = db["departments"].get(inv["department_id"])
    if dept is not None:
        dept["billed_ytd_cents"] += inv["total_cents"]
        touch(dept)
    return respond_object(serialize(inv))


@app.route("/chargeback-invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    inv = get_or_404("invoices", iid)
    if inv["status"] != "ISSUED":
        raise E_STATE("Invoice must be ISSUED to pay.")
    inv["status"] = "PAID"
    touch(inv)
    return respond_object(serialize(inv))


@app.route("/chargeback-invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    uid, role = require_auth()
    require_role(role, {"DepartmentUser"})
    inv = get_or_404("invoices", iid)
    if inv["department_id"] != uid:
        raise E_FORBIDDEN("DepartmentUser may only dispute its own invoices.")
    body = get_body()
    reason = require_present(body, "disputed_reason")
    if inv["status"] != "ISSUED":
        raise E_STATE("Invoice must be ISSUED to dispute.")
    inv["disputed_reason"] = reason
    inv["status"] = "DISPUTED"
    touch(inv)
    return respond_object(serialize(inv))


@app.route("/chargeback-invoices/<iid>/resolve", methods=["POST"])
def resolve_invoice(iid):
    _, role = require_auth()
    require_role(role, {"FinanceOfficer"})
    inv = get_or_404("invoices", iid)
    body = get_body()
    outcome = require_present(body, "outcome")
    if outcome not in OUTCOMES:
        raise E_VALIDATION("Invalid outcome.")
    if inv["status"] != "DISPUTED":
        raise E_STATE("Invoice must be DISPUTED to resolve.")
    if outcome == "REAFFIRM":
        inv["status"] = "ISSUED"
        touch(inv)
    else:
        inv["status"] = "ADJUSTED"
        touch(inv)
        dept = db["departments"].get(inv["department_id"])
        if dept is not None:
            dept["billed_ytd_cents"] -= inv["total_cents"]
            touch(dept)
    return respond_object(serialize(inv))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
