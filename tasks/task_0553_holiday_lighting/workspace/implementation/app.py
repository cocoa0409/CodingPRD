import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot; NO seeding)
# ---------------------------------------------------------------------------
DB = {
    "customers": {},
    "contracts": {},
    "estimates": {},
    "crews": {},
    "route_days": {},
    "route_assignments": {},
    "jobs": {},
    "service_calls": {},
    "storage_bins": {},
    "storage_records": {},
    "financing_plans": {},
    "payments": {},
    "invoices": {},
}

STATE = {"clock": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

KNOWN_ROLES = {"SalesRep", "Customer", "Dispatcher", "CrewLead", "BillingAdmin"}

COMPLEXITY_MULT = {"SIMPLE": Decimal("1.00"), "MODERATE": Decimal("1.15"), "COMPLEX": Decimal("1.30")}

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class APIError(Exception):
    def __init__(self, http_status, error_id, message=""):
        super().__init__(message or error_id)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message or error_id


def err(http, eid, msg=""):
    return APIError(http, eid, msg)


INVALID = lambda m="invalid request": APIError(422, "ERR_INVALID_REQUEST", m)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(STATE["clock"])


def parse_dt(s):
    if not isinstance(s, str):
        raise INVALID("bad datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        raise INVALID("bad datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(store, fields):
    ts = now_iso()
    rec = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}
    rec.update(fields)
    DB[store][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(APIError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def auth():
    role = request.headers.get("X-User-Role")
    if not role or role not in KNOWN_ROLES:
        raise APIError(401, "ERR_UNAUTHENTICATED", "missing or unknown role")
    return request.headers.get("X-User-ID"), role


def require(role, allowed):
    if role not in allowed:
        raise APIError(403, "ERR_UNAUTHORIZED", "role not permitted")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def v_present(b, name):
    return name in b and b[name] is not None


def v_str(b, name, required=True, default=None):
    if not v_present(b, name):
        if required:
            raise INVALID(f"missing {name}")
        return default
    v = b[name]
    if not isinstance(v, str):
        raise INVALID(f"{name} must be a string")
    return v


def v_int(b, name, minv=None, required=True, default=None):
    if not v_present(b, name):
        if required:
            raise INVALID(f"missing {name}")
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise INVALID(f"{name} must be an integer")
    if minv is not None and v < minv:
        raise INVALID(f"{name} out of range")
    return v


def v_bool(b, name, required=False, default=False):
    if not v_present(b, name):
        if required:
            raise INVALID(f"missing {name}")
        return default
    v = b[name]
    if not isinstance(v, bool):
        raise INVALID(f"{name} must be a boolean")
    return v


def v_enum(b, name, allowed, required=True, default=None):
    if not v_present(b, name):
        if required:
            raise INVALID(f"missing {name}")
        return default
    v = b[name]
    if v not in allowed:
        raise INVALID(f"{name} invalid")
    return v


def v_dt(b, name, required=True, default=None):
    if not v_present(b, name):
        if required:
            raise INVALID(f"missing {name}")
        return default
    v = b[name]
    parse_dt(v)  # validate parseable
    return v


NOT_FOUND_CODE = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "contracts": "ERR_CONTRACT_NOT_FOUND",
    "estimates": "ERR_ESTIMATE_NOT_FOUND",
    "crews": "ERR_CREW_NOT_FOUND",
    "route_days": "ERR_ROUTE_DAY_NOT_FOUND",
    "route_assignments": "ERR_ROUTE_ASSIGNMENT_NOT_FOUND",
    "jobs": "ERR_JOB_NOT_FOUND",
    "service_calls": "ERR_SERVICE_CALL_NOT_FOUND",
    "storage_bins": "ERR_STORAGE_BIN_NOT_FOUND",
    "storage_records": "ERR_STORAGE_RECORD_NOT_FOUND",
    "financing_plans": "ERR_FINANCING_PLAN_NOT_FOUND",
    "payments": "ERR_PAYMENT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
}


def get_path(store, rid):
    rec = DB[store].get(rid)
    if rec is None:
        raise APIError(404, NOT_FOUND_CODE[store], f"{store} not found")
    return rec


def fk_exists(b, name, store):
    """Verify a present body foreign key resolves; missing/None is left to field validation."""
    if not v_present(b, name):
        return None
    rid = b[name]
    rec = DB[store].get(rid)
    if rec is None:
        raise APIError(404, NOT_FOUND_CODE[store], f"{store} not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    limit = 10
    offset = 0
    if args.get("limit") is not None:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise INVALID("bad limit")
        limit = max(1, min(100, limit))
    if args.get("offset") is not None:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise INVALID("bad offset")
        offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def list_store(store, filters=None):
    items = list(DB[store].values())  # insertion order == created_at asc
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [r for r in items if str(r.get(key)) == str(val)]
    return items


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = auth()
    require(role, {"SalesRep", "Dispatcher", "BillingAdmin"})
    b = body()
    v_dt(b, "to_iso8601", required=True)
    STATE["clock"] = parse_dt(b["to_iso8601"])
    return ok({"current_utc": now_iso()}, 200)


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _uid, role = auth()
    require(role, {"SalesRep"})
    b = body()
    name = v_str(b, "name")
    addr = v_str(b, "service_address")
    roof = v_int(b, "roofline_feet", minv=0)
    rec = new_record("customers", {
        "name": name,
        "service_address": addr,
        "roofline_feet": roof,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    return ok(rec, 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _uid, role = auth()
    require(role, {"SalesRep", "Dispatcher", "BillingAdmin", "CrewLead", "Customer"})
    return ok(get_path("customers", cid), 200)


def recompute_balance(cust):
    total = sum(inv["total_cents"] for inv in DB["invoices"].values()
                if inv["customer_id"] == cust["id"] and inv["status"] == "ISSUED")
    cust["outstanding_balance_cents"] = total
    touch(cust)


# ===========================================================================
# Contracts
# ===========================================================================
@app.route("/contracts", methods=["POST"])
def create_contract():
    _uid, role = auth()
    require(role, {"SalesRep"})
    b = body()
    fk_exists(b, "customer_id", "customers")
    customer_id = v_str(b, "customer_id")
    contract_type = v_enum(b, "contract_type", {"SEASONAL_RENTAL", "PERMANENT_PURCHASE"})
    season_year = v_int(b, "season_year")
    base_fee = v_int(b, "base_season_fee_cents", minv=0)
    early_bird_cutoff = v_dt(b, "early_bird_cutoff")
    storage_included = v_bool(b, "storage_included", default=False)
    storage_surcharge = v_int(b, "storage_surcharge_cents", minv=0, required=False, default=0)
    rec = new_record("contracts", {
        "customer_id": customer_id,
        "contract_type": contract_type,
        "season_year": season_year,
        "base_season_fee_cents": base_fee,
        "storage_included": storage_included,
        "storage_surcharge_cents": storage_surcharge,
        "early_bird_cutoff": early_bird_cutoff,
        "signed_date": None,
        "early_bird": False,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "contract_price_cents": 0,
        "renewed_from_id": None,
        "status": "DRAFT",
    })
    return ok(rec, 201)


def price_contract(c):
    subtotal = c["base_season_fee_cents"] + (c["storage_surcharge_cents"] if c["storage_included"] else 0)
    signed = parse_dt(c["signed_date"])
    cutoff = parse_dt(c["early_bird_cutoff"])
    early_bird = signed <= cutoff
    if not early_bird:
        rate = Decimal("0")
    elif subtotal >= 100000:
        rate = Decimal("0.10")
    elif subtotal >= 50000:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0")
    discount = rhu(Decimal(subtotal) * rate)
    c["subtotal_cents"] = subtotal
    c["early_bird"] = early_bird
    c["discount_cents"] = discount
    c["contract_price_cents"] = subtotal - discount


@app.route("/contracts/<cid>/sign", methods=["POST"])
def sign_contract(cid):
    _uid, role = auth()
    require(role, {"SalesRep"})
    c = get_path("contracts", cid)
    if c["status"] != "DRAFT":
        raise APIError(409, "ERR_CONTRACT_NOT_SIGNABLE", "contract not signable")
    c["signed_date"] = now_iso()
    price_contract(c)
    c["status"] = "ACTIVE"
    touch(c)
    return ok(c, 200)


@app.route("/contracts/<cid>/renew", methods=["POST"])
def renew_contract(cid):
    _uid, role = auth()
    require(role, {"SalesRep"})
    c = get_path("contracts", cid)
    b = body()
    season_year = v_int(b, "season_year")
    base_fee = v_int(b, "base_season_fee_cents", minv=0)
    early_bird_cutoff = v_dt(b, "early_bird_cutoff")
    storage_included = v_bool(b, "storage_included", default=False)
    storage_surcharge = v_int(b, "storage_surcharge_cents", minv=0, required=False, default=0)
    if c["status"] != "ACTIVE":
        raise APIError(409, "ERR_CONTRACT_NOT_RENEWABLE", "contract not renewable")
    new_c = new_record("contracts", {
        "customer_id": c["customer_id"],
        "contract_type": c["contract_type"],
        "season_year": season_year,
        "base_season_fee_cents": base_fee,
        "storage_included": storage_included,
        "storage_surcharge_cents": storage_surcharge,
        "early_bird_cutoff": early_bird_cutoff,
        "signed_date": None,
        "early_bird": False,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "contract_price_cents": 0,
        "renewed_from_id": c["id"],
        "status": "DRAFT",
    })
    c["status"] = "RENEWED"
    touch(c)
    return ok(new_c, 201)


def cancel_job_internal(job):
    """Set job CANCELLED and run assignment-release + route-day recompute cascade."""
    job["status"] = "CANCELLED"
    touch(job)
    for a in DB["route_assignments"].values():
        if a["job_id"] == job["id"] and a["status"] in ("BOOKED", "DISPATCHED"):
            a["status"] = "RELEASED"
            touch(a)
            rd = DB["route_days"].get(a["route_day_id"])
            if rd is not None:
                recompute_booked_stops(rd)
                touch(rd)


@app.route("/contracts/<cid>/cancel", methods=["POST"])
def cancel_contract(cid):
    _uid, role = auth()
    require(role, {"SalesRep", "BillingAdmin"})
    c = get_path("contracts", cid)
    if c["status"] != "ACTIVE":
        raise APIError(409, "ERR_CONTRACT_NOT_ACTIVE", "contract not active")
    c["status"] = "CANCELLED"
    touch(c)
    for job in DB["jobs"].values():
        if job["contract_id"] == c["id"] and job["status"] in ("SCHEDULED", "RESCHEDULED"):
            cancel_job_internal(job)
    return ok(c, 200)


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    _uid, role = auth()
    require(role, {"SalesRep", "Dispatcher", "BillingAdmin", "Customer"})
    return ok(get_path("contracts", cid), 200)


@app.route("/contracts", methods=["GET"])
def list_contracts():
    _uid, role = auth()
    require(role, {"SalesRep", "Dispatcher", "BillingAdmin", "Customer"})
    items = list_store("contracts", {
        "customer_id": request.args.get("customer_id"),
        "status": request.args.get("status"),
        "renewed_from_id": request.args.get("renewed_from_id"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Estimates
# ===========================================================================
def compute_footage_total(product_line, footage, complexity, accessory_count):
    base = 15000 if product_line == "SEASONAL" else 40000
    t1 = min(footage, 100) * 300
    t2 = min(max(footage - 100, 0), 100) * 250
    t3 = max(footage - 200, 0) * 200
    footage_cost = t1 + t2 + t3
    complexity_cost = rhu(Decimal(footage_cost) * COMPLEXITY_MULT[complexity])
    accessory_cost = accessory_count * 1200
    return base + complexity_cost + accessory_cost


@app.route("/estimates", methods=["POST"])
def create_estimate():
    _uid, role = auth()
    require(role, {"SalesRep"})
    b = body()
    fk_exists(b, "customer_id", "customers")
    fk_exists(b, "contract_id", "contracts")
    customer_id = v_str(b, "customer_id")
    product_line = v_enum(b, "product_line", {"SEASONAL", "PERMANENT"})
    estimated_footage = v_int(b, "estimated_footage", minv=0)
    complexity = v_enum(b, "roofline_complexity", {"SIMPLE", "MODERATE", "COMPLEX"})
    contract_id = v_str(b, "contract_id", required=False, default=None)
    accessory_count = v_int(b, "accessory_count", minv=0, required=False, default=0)
    rec = new_record("estimates", {
        "customer_id": customer_id,
        "contract_id": contract_id,
        "product_line": product_line,
        "estimated_footage": estimated_footage,
        "roofline_complexity": complexity,
        "accessory_count": accessory_count,
        "quoted_total_cents": None,
        "measured_footage": None,
        "final_total_cents": None,
        "status": "DRAFT",
    })
    return ok(rec, 201)


@app.route("/estimates/<eid>/quote", methods=["POST"])
def quote_estimate(eid):
    _uid, role = auth()
    require(role, {"SalesRep"})
    e = get_path("estimates", eid)
    if e["status"] != "DRAFT":
        raise APIError(409, "ERR_ESTIMATE_NOT_DRAFT", "estimate not draft")
    e["quoted_total_cents"] = compute_footage_total(
        e["product_line"], e["estimated_footage"], e["roofline_complexity"], e["accessory_count"])
    e["status"] = "QUOTED"
    touch(e)
    return ok(e, 200)


@app.route("/estimates/<eid>/accept", methods=["POST"])
def accept_estimate(eid):
    uid, role = auth()
    require(role, {"Customer"})
    e = get_path("estimates", eid)
    if e["customer_id"] != uid:
        raise APIError(403, "ERR_UNAUTHORIZED", "not owner")
    if e["status"] != "QUOTED":
        raise APIError(409, "ERR_ESTIMATE_NOT_QUOTED", "estimate not quoted")
    e["status"] = "ACCEPTED"
    touch(e)
    return ok(e, 200)


@app.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    _uid, role = auth()
    require(role, {"SalesRep", "BillingAdmin", "Customer", "Dispatcher"})
    return ok(get_path("estimates", eid), 200)


@app.route("/estimates", methods=["GET"])
def list_estimates():
    _uid, role = auth()
    require(role, {"SalesRep", "BillingAdmin", "Customer", "Dispatcher"})
    items = list_store("estimates", {
        "customer_id": request.args.get("customer_id"),
        "contract_id": request.args.get("contract_id"),
        "status": request.args.get("status"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Crews
# ===========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    _uid, role = auth()
    require(role, {"Dispatcher"})
    b = body()
    name = v_str(b, "name")
    home_zone = v_str(b, "home_zone")
    capacity = v_int(b, "daily_stop_capacity", minv=1)
    active = v_bool(b, "active", default=True)
    rec = new_record("crews", {
        "name": name,
        "home_zone": home_zone,
        "daily_stop_capacity": capacity,
        "active": active,
    })
    return ok(rec, 201)


# ===========================================================================
# Route days
# ===========================================================================
def recompute_booked_stops(rd):
    rd["booked_stops"] = sum(
        1 for a in DB["route_assignments"].values()
        if a["route_day_id"] == rd["id"] and a["status"] in ("BOOKED", "DISPATCHED")
    )


@app.route("/route-days", methods=["POST"])
def create_route_day():
    _uid, role = auth()
    require(role, {"Dispatcher"})
    b = body()
    fk_exists(b, "crew_id", "crews")
    crew_id = v_str(b, "crew_id")
    service_date = v_dt(b, "service_date")
    zone = v_str(b, "zone")
    max_stops = v_int(b, "max_stops", minv=1)
    rec = new_record("route_days", {
        "crew_id": crew_id,
        "service_date": service_date,
        "zone": zone,
        "max_stops": max_stops,
        "booked_stops": 0,
        "status": "PLANNED",
    })
    return ok(rec, 201)


@app.route("/route-days/<rid>/dispatch", methods=["POST"])
def dispatch_route_day(rid):
    _uid, role = auth()
    require(role, {"Dispatcher"})
    rd = get_path("route_days", rid)
    if rd["status"] != "PLANNED":
        raise APIError(409, "ERR_ROUTE_DAY_NOT_PLANNED", "route day not planned")
    for a in DB["route_assignments"].values():
        if a["route_day_id"] == rd["id"] and a["status"] == "BOOKED":
            a["status"] = "DISPATCHED"
            touch(a)
    rd["status"] = "DISPATCHED"
    touch(rd)
    return ok(rd, 200)


@app.route("/route-days/<rid>", methods=["GET"])
def get_route_day(rid):
    _uid, role = auth()
    require(role, {"Dispatcher", "SalesRep", "BillingAdmin", "CrewLead"})
    return ok(get_path("route_days", rid), 200)


@app.route("/route-days", methods=["GET"])
def list_route_days():
    _uid, role = auth()
    require(role, {"Dispatcher", "SalesRep", "BillingAdmin", "CrewLead"})
    items = list_store("route_days", {
        "crew_id": request.args.get("crew_id"),
        "service_date": request.args.get("service_date"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Route assignments
# ===========================================================================
@app.route("/route-assignments", methods=["POST"])
def create_route_assignment():
    _uid, role = auth()
    require(role, {"Dispatcher"})
    b = body()
    rd = fk_exists(b, "route_day_id", "route_days")
    job = fk_exists(b, "job_id", "jobs")
    # field validation
    v_str(b, "route_day_id")
    v_str(b, "job_id")
    window_start = v_dt(b, "window_start")
    window_end = v_dt(b, "window_end")
    expected_version = v_int(b, "expected_route_day_version")
    # window well-formed
    ws = parse_dt(window_start)
    we = parse_dt(window_end)
    if not (we > ws):
        raise APIError(422, "ERR_INVALID_WINDOW", "window_end must be after window_start")
    # job bookable
    if job["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise APIError(409, "ERR_JOB_NOT_BOOKABLE", "job not bookable")
    # window overlap on same route day (half-open)
    for a in DB["route_assignments"].values():
        if a["route_day_id"] == rd["id"] and a["status"] in ("BOOKED", "DISPATCHED"):
            a_start = parse_dt(a["window_start"])
            a_end = parse_dt(a["window_end"])
            if ws < a_end and a_start < we:
                raise APIError(409, "ERR_WINDOW_OVERLAP", "window overlaps")
    # capacity
    recompute_booked_stops(rd)
    if rd["booked_stops"] >= rd["max_stops"]:
        raise APIError(409, "ERR_ROUTE_DAY_FULL", "route day full")
    # optimistic concurrency (final gate)
    if expected_version != rd["version"]:
        raise APIError(412, "ERR_STALE_VERSION", "stale route day version")
    rec = new_record("route_assignments", {
        "route_day_id": rd["id"],
        "job_id": job["id"],
        "window_start": window_start,
        "window_end": window_end,
        "status": "BOOKED",
    })
    recompute_booked_stops(rd)
    touch(rd)
    return ok(rec, 201)


@app.route("/route-assignments/<aid>", methods=["GET"])
def get_route_assignment(aid):
    _uid, role = auth()
    require(role, {"Dispatcher", "SalesRep", "BillingAdmin", "CrewLead"})
    return ok(get_path("route_assignments", aid), 200)


@app.route("/route-assignments", methods=["GET"])
def list_route_assignments():
    _uid, role = auth()
    require(role, {"Dispatcher", "SalesRep", "BillingAdmin", "CrewLead"})
    items = list_store("route_assignments", {
        "route_day_id": request.args.get("route_day_id"),
        "job_id": request.args.get("job_id"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Jobs
# ===========================================================================
@app.route("/jobs", methods=["POST"])
def create_job():
    _uid, role = auth()
    require(role, {"Dispatcher"})
    b = body()
    contract = fk_exists(b, "contract_id", "contracts")
    fk_exists(b, "estimate_id", "estimates")
    v_str(b, "contract_id")
    job_type = v_enum(b, "job_type", {"INSTALL", "TAKEDOWN", "SERVICE"})
    scheduled_date = v_dt(b, "scheduled_date")
    estimate_id = v_str(b, "estimate_id", required=False, default=None)
    if contract["status"] != "ACTIVE":
        raise APIError(409, "ERR_CONTRACT_NOT_ACTIVE", "contract not active")
    rec = new_record("jobs", {
        "contract_id": contract["id"],
        "estimate_id": estimate_id,
        "job_type": job_type,
        "scheduled_date": scheduled_date,
        "completed_footage": None,
        "reschedule_count": 0,
        "status": "SCHEDULED",
    })
    return ok(rec, 201)


@app.route("/jobs/<jid>/weather-hold", methods=["POST"])
def weather_hold_job(jid):
    _uid, role = auth()
    require(role, {"Dispatcher"})
    job = get_path("jobs", jid)
    if job["status"] != "SCHEDULED":
        raise APIError(409, "ERR_JOB_NOT_SCHEDULED", "job not scheduled")
    job["status"] = "RESCHEDULED"
    touch(job)
    return ok(job, 200)


@app.route("/jobs/<jid>/reschedule", methods=["POST"])
def reschedule_job(jid):
    _uid, role = auth()
    require(role, {"Dispatcher"})
    job = get_path("jobs", jid)
    b = body()
    new_date = v_dt(b, "new_scheduled_date")
    if job["status"] != "RESCHEDULED":
        raise APIError(409, "ERR_JOB_NOT_HELD", "job not held")
    job["status"] = "SCHEDULED"
    job["scheduled_date"] = new_date
    job["reschedule_count"] += 1
    touch(job)
    return ok(job, 200)


def crew_owns_job(job, uid):
    for a in DB["route_assignments"].values():
        if a["job_id"] == job["id"]:
            rd = DB["route_days"].get(a["route_day_id"])
            if rd is not None and rd["crew_id"] == uid:
                return True
    return False


@app.route("/jobs/<jid>/start", methods=["POST"])
def start_job(jid):
    uid, role = auth()
    require(role, {"CrewLead"})
    job = get_path("jobs", jid)
    # ownership
    if not crew_owns_job(job, uid):
        raise APIError(403, "ERR_UNAUTHORIZED", "not owner")
    # state
    if job["status"] != "SCHEDULED":
        raise APIError(409, "ERR_JOB_NOT_SCHEDULED", "job not scheduled")
    # cross-entity: dispatched route day
    dispatched = any(
        a["job_id"] == job["id"]
        and (DB["route_days"].get(a["route_day_id"]) or {}).get("status") == "DISPATCHED"
        for a in DB["route_assignments"].values()
    )
    if not dispatched:
        raise APIError(409, "ERR_ROUTE_DAY_NOT_DISPATCHED", "route day not dispatched")
    job["status"] = "IN_PROGRESS"
    touch(job)
    return ok(job, 200)


@app.route("/jobs/<jid>/complete", methods=["POST"])
def complete_job(jid):
    uid, role = auth()
    require(role, {"CrewLead"})
    job = get_path("jobs", jid)
    b = body()
    if not crew_owns_job(job, uid):
        raise APIError(403, "ERR_UNAUTHORIZED", "not owner")
    if job["status"] != "IN_PROGRESS":
        raise APIError(409, "ERR_JOB_NOT_IN_PROGRESS", "job not in progress")
    if job["job_type"] == "INSTALL":
        completed_footage = v_int(b, "completed_footage", minv=0)
        job["completed_footage"] = completed_footage
        if job["estimate_id"]:
            e = DB["estimates"].get(job["estimate_id"])
            if e is not None and e["status"] == "ACCEPTED":
                e["measured_footage"] = completed_footage
                e["final_total_cents"] = compute_footage_total(
                    e["product_line"], completed_footage, e["roofline_complexity"], e["accessory_count"])
                e["status"] = "INVOICED"
                touch(e)
    job["status"] = "COMPLETED"
    touch(job)
    return ok(job, 200)


@app.route("/jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    _uid, role = auth()
    require(role, {"Dispatcher"})
    job = get_path("jobs", jid)
    if job["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise APIError(409, "ERR_JOB_NOT_CANCELLABLE", "job not cancellable")
    cancel_job_internal(job)
    return ok(job, 200)


@app.route("/jobs/<jid>", methods=["GET"])
def get_job(jid):
    _uid, role = auth()
    require(role, {"Dispatcher", "SalesRep", "BillingAdmin", "CrewLead", "Customer"})
    return ok(get_path("jobs", jid), 200)


@app.route("/jobs", methods=["GET"])
def list_jobs():
    _uid, role = auth()
    require(role, {"Dispatcher", "SalesRep", "BillingAdmin", "CrewLead", "Customer"})
    items = list_store("jobs", {
        "contract_id": request.args.get("contract_id"),
        "estimate_id": request.args.get("estimate_id"),
        "status": request.args.get("status"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Service calls
# ===========================================================================
@app.route("/service-calls", methods=["POST"])
def create_service_call():
    _uid, role = auth()
    require(role, {"Customer", "BillingAdmin"})
    b = body()
    contract = fk_exists(b, "contract_id", "contracts")
    v_str(b, "contract_id")
    reported_issue = v_str(b, "reported_issue")
    cause = v_enum(b, "cause", {"WEATHER", "DEFECT", "VANDALISM"})
    service_fee = v_int(b, "service_fee_cents", minv=0, required=False, default=0)
    rec = new_record("service_calls", {
        "contract_id": contract["id"],
        "job_id": None,
        "reported_issue": reported_issue,
        "cause": cause,
        "service_fee_cents": service_fee,
        "classification": None,
        "status": "OPEN",
    })
    return ok(rec, 201)


@app.route("/service-calls/<sid>/classify", methods=["POST"])
def classify_service_call(sid):
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    sc = get_path("service_calls", sid)
    b = body()
    classification = v_enum(b, "classification", {"WARRANTY", "BILLABLE"})
    if sc["status"] != "OPEN":
        raise APIError(409, "ERR_SERVICE_CALL_INVALID_STATE", "service call not open")
    sc["classification"] = classification
    sc["status"] = "CLASSIFIED"
    touch(sc)
    return ok(sc, 200)


@app.route("/service-calls/<sid>/schedule", methods=["POST"])
def schedule_service_call(sid):
    _uid, role = auth()
    require(role, {"Dispatcher"})
    sc = get_path("service_calls", sid)
    b = body()
    scheduled_date = v_dt(b, "scheduled_date")
    if sc["status"] != "CLASSIFIED":
        raise APIError(409, "ERR_SERVICE_CALL_INVALID_STATE", "service call not classified")
    contract = DB["contracts"].get(sc["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise APIError(409, "ERR_CONTRACT_NOT_ACTIVE", "contract not active")
    job = new_record("jobs", {
        "contract_id": sc["contract_id"],
        "estimate_id": None,
        "job_type": "SERVICE",
        "scheduled_date": scheduled_date,
        "completed_footage": None,
        "reschedule_count": 0,
        "status": "SCHEDULED",
    })
    sc["job_id"] = job["id"]
    sc["status"] = "SCHEDULED"
    touch(sc)
    return ok(sc, 200)


@app.route("/service-calls/<sid>/resolve", methods=["POST"])
def resolve_service_call(sid):
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    sc = get_path("service_calls", sid)
    if sc["status"] != "SCHEDULED":
        raise APIError(409, "ERR_SERVICE_CALL_INVALID_STATE", "service call not scheduled")
    if sc["classification"] == "BILLABLE":
        contract = DB["contracts"].get(sc["contract_id"])
        customer_id = contract["customer_id"] if contract else None
        line_items = [{
            "description": sc["reported_issue"],
            "amount_cents": sc["service_fee_cents"],
            "taxable": False,
        }]
        subtotal, tax, total = compute_invoice_totals(line_items, 0)
        inv = new_record("invoices", {
            "customer_id": customer_id,
            "job_id": sc["job_id"],
            "source_type": "SERVICE",
            "line_items": line_items,
            "tax_rate_bps": 0,
            "subtotal_cents": subtotal,
            "tax_cents": tax,
            "total_cents": total,
            "status": "ISSUED",
        })
        cust = DB["customers"].get(customer_id)
        if cust is not None:
            recompute_balance(cust)
    sc["status"] = "RESOLVED"
    touch(sc)
    return ok(sc, 200)


@app.route("/service-calls/<sid>", methods=["GET"])
def get_service_call(sid):
    _uid, role = auth()
    require(role, {"BillingAdmin", "Dispatcher", "SalesRep", "Customer"})
    return ok(get_path("service_calls", sid), 200)


@app.route("/service-calls", methods=["GET"])
def list_service_calls():
    _uid, role = auth()
    require(role, {"BillingAdmin", "Dispatcher", "SalesRep", "Customer"})
    items = list_store("service_calls", {
        "contract_id": request.args.get("contract_id"),
        "job_id": request.args.get("job_id"),
        "status": request.args.get("status"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Storage
# ===========================================================================
@app.route("/storage-bins", methods=["POST"])
def create_storage_bin():
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    b = body()
    bin_code = v_str(b, "bin_code")
    warehouse_zone = v_str(b, "warehouse_zone")
    buffer_days = v_int(b, "buffer_days", minv=0, required=False, default=0)
    rec = new_record("storage_bins", {
        "bin_code": bin_code,
        "warehouse_zone": warehouse_zone,
        "buffer_days": buffer_days,
    })
    return ok(rec, 201)


@app.route("/storage-records", methods=["POST"])
def create_storage_record():
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    b = body()
    contract = fk_exists(b, "contract_id", "contracts")
    bin_rec = fk_exists(b, "storage_bin_id", "storage_bins")
    v_str(b, "contract_id")
    v_str(b, "storage_bin_id")
    stored_from = v_dt(b, "stored_from")
    stored_until = v_dt(b, "stored_until")
    nf = parse_dt(stored_from)
    nu = parse_dt(stored_until)
    buffer = timedelta(days=bin_rec["buffer_days"])
    inflated_from = nf - buffer
    inflated_until = nu + buffer
    for r in DB["storage_records"].values():
        if r["storage_bin_id"] == bin_rec["id"] and r["status"] == "STORED":
            ef = parse_dt(r["stored_from"])
            eu = parse_dt(r["stored_until"])
            if inflated_from <= eu and ef <= inflated_until:
                raise APIError(409, "ERR_BIN_OCCUPIED", "bin occupied")
    rec = new_record("storage_records", {
        "contract_id": contract["id"],
        "storage_bin_id": bin_rec["id"],
        "stored_from": stored_from,
        "stored_until": stored_until,
        "status": "STORED",
    })
    return ok(rec, 201)


@app.route("/storage-records/<rid>/retrieve", methods=["POST"])
def retrieve_storage_record(rid):
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    r = get_path("storage_records", rid)
    if r["status"] != "STORED":
        raise APIError(409, "ERR_STORAGE_RECORD_NOT_STORED", "record not stored")
    contract = DB["contracts"].get(r["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise APIError(409, "ERR_CONTRACT_NOT_ACTIVE", "contract not active")
    r["status"] = "RETRIEVED"
    touch(r)
    return ok(r, 200)


@app.route("/storage-records/<rid>", methods=["GET"])
def get_storage_record(rid):
    _uid, role = auth()
    require(role, {"BillingAdmin", "SalesRep", "Customer"})
    return ok(get_path("storage_records", rid), 200)


@app.route("/storage-records", methods=["GET"])
def list_storage_records():
    _uid, role = auth()
    require(role, {"BillingAdmin", "SalesRep", "Customer"})
    items = list_store("storage_records", {
        "contract_id": request.args.get("contract_id"),
        "storage_bin_id": request.args.get("storage_bin_id"),
        "status": request.args.get("status"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Financing
# ===========================================================================
@app.route("/financing-plans", methods=["POST"])
def create_financing_plan():
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    b = body()
    contract = fk_exists(b, "contract_id", "contracts")
    v_str(b, "contract_id")
    principal = v_int(b, "original_principal_cents", minv=1)
    apr_bps = v_int(b, "apr_bps", minv=0)
    term_months = v_int(b, "term_months", minv=1)
    total_interest = rhu(Decimal(principal) * Decimal(apr_bps) / Decimal(10000) * Decimal(term_months) / Decimal(12))
    monthly_payment = rhu(Decimal(principal + total_interest) / Decimal(term_months))
    rec = new_record("financing_plans", {
        "contract_id": contract["id"],
        "original_principal_cents": principal,
        "apr_bps": apr_bps,
        "term_months": term_months,
        "total_interest_cents": total_interest,
        "monthly_payment_cents": monthly_payment,
        "remaining_principal_cents": principal,
        "status": "ACTIVE",
    })
    return ok(rec, 201)


@app.route("/financing-plans/<pid>/payoff-quote", methods=["GET"])
def payoff_quote(pid):
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    plan = get_path("financing_plans", pid)
    posted = sum(1 for p in DB["payments"].values()
                 if p["financing_plan_id"] == plan["id"] and p["status"] == "POSTED")
    remaining_installments = plan["term_months"] - posted
    scheduled = plan["monthly_payment_cents"] * remaining_installments
    early = plan["remaining_principal_cents"] + rhu(Decimal(plan["remaining_principal_cents"]) * Decimal(200) / Decimal(10000))
    return ok({
        "scheduled_remaining_cents": scheduled,
        "early_payoff_cents": early,
        "remaining_principal_cents": plan["remaining_principal_cents"],
        "remaining_installments": remaining_installments,
    }, 200)


@app.route("/financing-plans/<pid>/payments", methods=["POST"])
def post_payment(pid):
    uid, role = auth()
    require(role, {"Customer", "BillingAdmin"})
    plan = get_path("financing_plans", pid)
    b = body()
    amount = v_int(b, "amount_cents", minv=1)
    if role == "Customer":
        contract = DB["contracts"].get(plan["contract_id"])
        if contract is None or contract["customer_id"] != uid:
            raise APIError(403, "ERR_UNAUTHORIZED", "not owner")
    if plan["status"] != "ACTIVE":
        raise APIError(409, "ERR_PLAN_NOT_ACTIVE", "plan not active")
    interest_portion = rhu(Decimal(plan["total_interest_cents"]) / Decimal(plan["term_months"]))
    principal_portion = amount - interest_portion
    if principal_portion > plan["remaining_principal_cents"]:
        raise APIError(422, "ERR_OVERPAYMENT", "overpayment")
    pay = new_record("payments", {
        "financing_plan_id": plan["id"],
        "amount_cents": amount,
        "interest_portion_cents": interest_portion,
        "principal_portion_cents": principal_portion,
        "payment_date": now_iso(),
        "status": "POSTED",
    })
    plan["remaining_principal_cents"] -= principal_portion
    if plan["remaining_principal_cents"] == 0:
        plan["status"] = "PAID_OFF"
    touch(plan)
    return ok(pay, 201)


@app.route("/financing-plans/<pid>", methods=["GET"])
def get_financing_plan(pid):
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    return ok(get_path("financing_plans", pid), 200)


@app.route("/financing-plans", methods=["GET"])
def list_financing_plans():
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    items = list_store("financing_plans", {
        "contract_id": request.args.get("contract_id"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.route("/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    pay = get_path("payments", pid)
    if pay["status"] != "POSTED":
        raise APIError(409, "ERR_PAYMENT_NOT_POSTED", "payment not posted")
    plan = DB["financing_plans"].get(pay["financing_plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise APIError(409, "ERR_PLAN_NOT_ACTIVE", "plan not active")
    plan["remaining_principal_cents"] += pay["principal_portion_cents"]
    touch(plan)
    pay["status"] = "REVERSED"
    touch(pay)
    return ok(pay, 200)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    return ok(get_path("payments", pid), 200)


@app.route("/payments", methods=["GET"])
def list_payments():
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    items = list_store("payments", {
        "financing_plan_id": request.args.get("financing_plan_id"),
        "status": request.args.get("status"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Invoices
# ===========================================================================
def compute_invoice_totals(line_items, tax_rate_bps):
    subtotal = sum(li["amount_cents"] for li in line_items)
    tax = 0
    for li in line_items:
        if li.get("taxable"):
            tax += rhu(Decimal(li["amount_cents"]) * Decimal(tax_rate_bps) / Decimal(10000))
    total = subtotal + tax
    return subtotal, tax, total


@app.route("/invoices", methods=["POST"])
def create_invoice():
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    b = body()
    customer = fk_exists(b, "customer_id", "customers")
    fk_exists(b, "job_id", "jobs")
    v_str(b, "customer_id")
    source_type = v_enum(b, "source_type", {"INSTALL", "STORAGE", "SERVICE", "MANUAL"})
    if not v_present(b, "line_items") or not isinstance(b["line_items"], list):
        raise INVALID("line_items required")
    line_items = []
    for li in b["line_items"]:
        if not isinstance(li, dict):
            raise INVALID("bad line item")
        amount = li.get("amount_cents")
        taxable = li.get("taxable")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise INVALID("bad line item amount")
        if not isinstance(taxable, bool):
            raise INVALID("bad line item taxable")
        line_items.append({
            "description": li.get("description"),
            "amount_cents": amount,
            "taxable": taxable,
        })
    tax_rate_bps = v_int(b, "tax_rate_bps", minv=0, required=False, default=0)
    job_id = v_str(b, "job_id", required=False, default=None)
    subtotal, tax, total = compute_invoice_totals(line_items, tax_rate_bps)
    rec = new_record("invoices", {
        "customer_id": customer["id"],
        "job_id": job_id,
        "source_type": source_type,
        "line_items": line_items,
        "tax_rate_bps": tax_rate_bps,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "status": "ISSUED",
    })
    recompute_balance(customer)
    return ok(rec, 201)


@app.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    _uid, role = auth()
    require(role, {"BillingAdmin"})
    inv = get_path("invoices", iid)
    if inv["status"] != "ISSUED":
        raise APIError(409, "ERR_INVOICE_NOT_ISSUED", "invoice not issued")
    inv["status"] = "VOID"
    touch(inv)
    cust = DB["customers"].get(inv["customer_id"])
    if cust is not None:
        recompute_balance(cust)
    return ok(inv, 200)


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    return ok(get_path("invoices", iid), 200)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    _uid, role = auth()
    require(role, {"BillingAdmin", "Customer", "SalesRep"})
    items = list_store("invoices", {
        "customer_id": request.args.get("customer_id"),
        "job_id": request.args.get("job_id"),
        "status": request.args.get("status"),
    })
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
