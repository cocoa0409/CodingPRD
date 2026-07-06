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
# Logical clock (reset on every fresh process boot)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}


def clock_now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def all_of_type(t):
    return [e for e in DB.values() if e["_type"] == t]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_MISSING_AUTH_HEADERS": 400,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_TECH_IDENTITY_MISMATCH": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_INSPECTION_LEVEL": 400,
    "ERR_INVALID_CREOSOTE_CLASS": 400,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_CHIMNEY_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_ROUTE_DAY_NOT_FOUND": 404,
    "ERR_SERVICE_JOB_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_REPAIR_ORDER_NOT_FOUND": 404,
    "ERR_WARRANTY_NOT_FOUND": 404,
    "ERR_REMINDER_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_JOB_NOT_IN_PROGRESS": 409,
    "ERR_JOB_HAS_OPEN_REPAIRS": 409,
    "ERR_JOB_TERMINAL": 409,
    "ERR_REPAIR_NOT_COMPLETED": 409,
    "ERR_WARRANTY_NOT_CLAIMABLE": 409,
    "ERR_REMINDER_NOT_DUE": 409,
    "ERR_INVALID_APPOINTMENT_WINDOW": 422,
    "ERR_APPOINTMENT_OUTSIDE_WINDOW": 422,
    "ERR_WARRANTY_EXPIRED": 422,
    "ERR_JOB_UNSAFE": 403,
    "ERR_PART_REQUIRED": 422,
    "ERR_UNKNOWN_PART": 422,
    "ERR_TECHNICIAN_DOUBLE_BOOKED": 409,
    "ERR_REPAIR_COST_EXCEEDS_AUTH": 402,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 402,
    "ERR_STALE_CHIMNEY_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "Invalid datetime")
    m = _ISO_RE.match(s.strip())
    if not m:
        raise ApiError("ERR_VALIDATION", "Invalid datetime format")
    year, mon, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    off = m.group(8)
    if off in (None, "Z", "z"):
        tz = timezone.utc
    else:
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        oh = int(off[:2])
        om = int(off[2:4])
        tz = timezone(sign * timedelta(hours=oh, minutes=om))
    try:
        dt = datetime(year, mon, day, hh, mm, ss, micro, tzinfo=tz)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Invalid datetime value")
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - datetime(year, month, 1)).days


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def months_between(a, b):
    """Whole calendar months from a to b, floored (>=0 assumed a<=b)."""
    months = (b.year - a.year) * 12 + (b.month - a.month)
    a_key = (a.day, a.hour, a.minute, a.second, a.microsecond)
    b_key = (b.day, b.hour, b.minute, b.second, b.microsecond)
    if b_key < a_key:
        months -= 1
    return months


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------
SWEEP_BASE_CENTS = {1: 15000, 2: 24000, 3: 40000}
CREOSOTE_SURCHARGE_CENTS = {1: 0, 2: 6000, 3: 18000}
GLAZE_SURCHARGE_CENTS = 5000
TRIP_FEE_CENTS = {"A": 0, "B": 3500, "C": 7000}
DISPOSAL_FEE_RATE = Decimal("0.045")
TRAVEL_BUFFER_SECONDS = 30 * 60
CO_UNSAFE_PPM = 9
CO_CONDEMN_PPM = 70

PART_CATALOG = {
    "CAP": {"CAP-STD", "CAP-SS"},
    "LINER": {"LNR-SS6", "LNR-AL"},
    "DAMPER": {"DMP-TOP", "DMP-THR"},
}


def sweep_cost(inspection_level, creosote_class, glaze_present, trip_zone):
    return (
        SWEEP_BASE_CENTS[inspection_level]
        + CREOSOTE_SURCHARGE_CENTS[creosote_class]
        + (GLAZE_SURCHARGE_CENTS if glaze_present else 0)
        + TRIP_FEE_CENTS[trip_zone]
    )


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
COMMON = "common"
LEAN = "lean"


def new_entity(etype, fields, kind=COMMON):
    now = datetime.now(timezone.utc)
    e = {"_type": etype, "_seq": next_seq(), "id": str(uuid.uuid4())}
    e["created_at"] = now
    if kind == COMMON:
        e["updated_at"] = now
        e["version"] = 1
    e.update(fields)
    DB[e["id"]] = e
    return e


def touch(e):
    if "version" in e:
        e["updated_at"] = datetime.now(timezone.utc)
        e["version"] += 1


def get_entity(eid, etype, err):
    e = DB.get(eid)
    if e is None or e["_type"] != etype:
        raise ApiError(err)
    return e


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(e):
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    if e["_type"] == "ReminderSchedule":
        out["is_due"] = e["status"] == "ACTIVE" and clock_now() >= e["next_due_date"]
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_array(items, page_meta, code=200):
    return (
        jsonify(
            {"meta": _meta(page_meta), "response_type": "array", "data": items}
        ),
        code,
    )


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
ROLES = {"Dispatcher", "Technician", "BillingClerk"}


def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    return uid, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Body must be an object")
    return data


def require(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError("ERR_VALIDATION", "Missing field: %s" % field)
    return v


def require_int(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field must be integer: %s" % field)
    return v


def opt_int(body, field, default):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field must be integer: %s" % field)
    return v


def opt_bool(body, field, default):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Field must be boolean: %s" % field)
    return v


def parse_pagination(args):
    def pint(name, default):
        raw = args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "Invalid %s" % name)

    limit = pint("limit", 10)
    offset = pint("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, args):
    items = sorted(items, key=lambda e: e["_seq"])
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    page_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serialize(e) for e in page], page_meta


# ---------------------------------------------------------------------------
# Derived recomputations
# ---------------------------------------------------------------------------
def recompute_booked(route_day):
    total = 0
    for a in all_of_type("Appointment"):
        if a["route_day_id"] == route_day["id"] and a["status"] not in ("CANCELLED", "NO_SHOW"):
            total += a["on_site_minutes"]
    if route_day["booked_minutes"] != total:
        route_day["booked_minutes"] = total
        touch(route_day)
    return total


def committed_value(job):
    total = job["sweep_provisional_cost_cents"]
    for ro in all_of_type("RepairOrder"):
        if ro["service_job_id"] == job["id"] and ro["status"] not in ("REJECTED", "CANCELLED"):
            total += ro["provisional_cost_cents"]
    return total


def recompute_committed(job):
    val = committed_value(job)
    if job["committed_cost_cents"] != val:
        job["committed_cost_cents"] = val
        touch(job)


# =============================================================================
# Customer
# =============================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    auth({"Dispatcher"})
    b = body_json()
    e = new_entity("Customer", {
        "name": require(b, "name"),
        "service_address": require(b, "service_address"),
        "phone": require(b, "phone"),
        "email": b.get("email"),
    })
    return ok_object(serialize(e), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    auth(ROLES)
    e = get_entity(cid, "Customer", "ERR_CUSTOMER_NOT_FOUND")
    return ok_object(serialize(e))


# =============================================================================
# Chimney
# =============================================================================
CHIMNEY_TYPES = {"MASONRY", "PREFAB_METAL", "FACTORY_BUILT"}
APPLIANCE_TYPES = {"WOOD_STOVE", "OPEN_FIREPLACE", "GAS_INSERT", "PELLET"}
LINER_TYPES = {"NONE", "CLAY", "STAINLESS", "ALUMINUM"}
DAMPER_TYPES = {"THROAT", "TOP_MOUNT", "NONE"}


@app.route("/chimneys", methods=["POST"])
def create_chimney():
    auth({"Dispatcher"})
    b = body_json()
    customer_id = require(b, "customer_id")
    get_entity(customer_id, "Customer", "ERR_CUSTOMER_NOT_FOUND")
    chimney_type = require(b, "chimney_type")
    appliance_type = require(b, "appliance_type")
    flue_count = require_int(b, "flue_count")
    if chimney_type not in CHIMNEY_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid chimney_type")
    if appliance_type not in APPLIANCE_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid appliance_type")
    if flue_count < 1:
        raise ApiError("ERR_VALIDATION", "flue_count must be >= 1")
    liner_type = b.get("liner_type", "NONE")
    damper_type = b.get("damper_type", "THROAT")
    cap_installed = opt_bool(b, "cap_installed", False)
    if liner_type not in LINER_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid liner_type")
    if damper_type not in DAMPER_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid damper_type")
    e = new_entity("Chimney", {
        "customer_id": customer_id,
        "chimney_type": chimney_type,
        "appliance_type": appliance_type,
        "flue_count": flue_count,
        "cap_installed": cap_installed,
        "liner_type": liner_type,
        "damper_type": damper_type,
        "last_service_date": None,
    })
    return ok_object(serialize(e), 201)


@app.route("/chimneys/<cid>", methods=["GET"])
def get_chimney(cid):
    auth(ROLES)
    e = get_entity(cid, "Chimney", "ERR_CHIMNEY_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/chimneys", methods=["GET"])
def list_chimneys():
    auth(ROLES)
    items = all_of_type("Chimney")
    cust = request.args.get("customer_id")
    if cust:
        items = [e for e in items if e["customer_id"] == cust]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


# =============================================================================
# Technician
# =============================================================================
CERT_LEVELS = {"CSIA_BASIC", "CSIA_ADVANCED", "MASTER"}


@app.route("/technicians", methods=["POST"])
def create_technician():
    auth({"Dispatcher"})
    b = body_json()
    name = require(b, "name")
    cert_level = require(b, "cert_level")
    if cert_level not in CERT_LEVELS:
        raise ApiError("ERR_VALIDATION", "Invalid cert_level")
    e = new_entity("Technician", {"name": name, "cert_level": cert_level})
    return ok_object(serialize(e), 201)


# =============================================================================
# RouteDay
# =============================================================================
@app.route("/route-days", methods=["POST"])
def create_route_day():
    auth({"Dispatcher"})
    b = body_json()
    technician_id = require(b, "technician_id")
    get_entity(technician_id, "Technician", "ERR_TECHNICIAN_NOT_FOUND")
    service_date = require(b, "service_date")
    window_start_ts = require_int(b, "window_start_ts")
    window_end_ts = require_int(b, "window_end_ts")
    capacity_minutes = require_int(b, "capacity_minutes")
    if window_end_ts <= window_start_ts:
        raise ApiError("ERR_VALIDATION", "window_end_ts must be > window_start_ts")
    if capacity_minutes < 0:
        raise ApiError("ERR_VALIDATION", "capacity_minutes must be >= 0")
    e = new_entity("RouteDay", {
        "technician_id": technician_id,
        "service_date": service_date,
        "window_start_ts": window_start_ts,
        "window_end_ts": window_end_ts,
        "capacity_minutes": capacity_minutes,
        "booked_minutes": 0,
    })
    return ok_object(serialize(e), 201)


@app.route("/route-days/<rid>", methods=["GET"])
def get_route_day(rid):
    auth(ROLES)
    e = get_entity(rid, "RouteDay", "ERR_ROUTE_DAY_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/route-days", methods=["GET"])
def list_route_days():
    auth(ROLES)
    items = all_of_type("RouteDay")
    tech = request.args.get("technician_id")
    if tech:
        items = [e for e in items if e["technician_id"] == tech]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


# =============================================================================
# ServiceJob
# =============================================================================
TRIP_ZONES = {"A", "B", "C"}
FLUE_ASSESSMENTS = {"UNASSESSED", "PASS", "DEFECTS", "BLOCKED"}


@app.route("/service-jobs", methods=["POST"])
def create_service_job():
    auth({"Dispatcher"})
    b = body_json()
    customer_id = require(b, "customer_id")
    get_entity(customer_id, "Customer", "ERR_CUSTOMER_NOT_FOUND")
    chimney_id = require(b, "chimney_id")
    get_entity(chimney_id, "Chimney", "ERR_CHIMNEY_NOT_FOUND")
    inspection_level = require(b, "inspection_level")
    if isinstance(inspection_level, bool) or inspection_level not in (1, 2, 3):
        raise ApiError("ERR_INVALID_INSPECTION_LEVEL")
    expected_creosote_class = b.get("expected_creosote_class", 1)
    if isinstance(expected_creosote_class, bool) or expected_creosote_class not in (1, 2, 3):
        raise ApiError("ERR_INVALID_CREOSOTE_CLASS")
    trip_zone = b.get("trip_zone", "A")
    if trip_zone not in TRIP_ZONES:
        raise ApiError("ERR_VALIDATION", "Invalid trip_zone")
    repair_authorization_cents = opt_int(b, "repair_authorization_cents", 0)
    if repair_authorization_cents < 0:
        raise ApiError("ERR_VALIDATION", "repair_authorization_cents must be >= 0")
    provisional = sweep_cost(inspection_level, expected_creosote_class, False, trip_zone)
    e = new_entity("ServiceJob", {
        "customer_id": customer_id,
        "chimney_id": chimney_id,
        "inspection_level": inspection_level,
        "expected_creosote_class": expected_creosote_class,
        "trip_zone": trip_zone,
        "repair_authorization_cents": repair_authorization_cents,
        "job_status": "DRAFT",
        "safety_posture": "PENDING",
        "flue_assessment": "UNASSESSED",
        "sweep_provisional_cost_cents": provisional,
        "sweep_final_cost_cents": None,
        "committed_cost_cents": provisional,
        "invoice_total_cents": None,
    })
    return ok_object(serialize(e), 201)


@app.route("/service-jobs/<jid>", methods=["GET"])
def get_service_job(jid):
    auth(ROLES)
    e = get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/service-jobs", methods=["GET"])
def list_service_jobs():
    auth(ROLES)
    items = all_of_type("ServiceJob")
    cust = request.args.get("customer_id")
    chim = request.args.get("chimney_id")
    st = request.args.get("job_status")
    if cust:
        items = [e for e in items if e["customer_id"] == cust]
    if chim:
        items = [e for e in items if e["chimney_id"] == chim]
    if st:
        items = [e for e in items if e["job_status"] == st]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


@app.route("/service-jobs/<jid>/inspect", methods=["POST"])
def inspect_job(jid):
    auth({"Technician"})
    job = get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    b = body_json()
    flue_assessment = require(b, "flue_assessment")
    if flue_assessment not in FLUE_ASSESSMENTS:
        raise ApiError("ERR_VALIDATION", "Invalid flue_assessment")
    job["flue_assessment"] = flue_assessment
    if flue_assessment == "BLOCKED":
        job["safety_posture"] = "CONDEMNED"
    touch(job)
    return ok_object(serialize(job))


@app.route("/service-jobs/<jid>/sweep", methods=["POST"])
def sweep_job(jid):
    auth({"Technician"})
    job = get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    b = body_json()
    measured = require(b, "measured_creosote_class")
    if isinstance(measured, bool) or measured not in (1, 2, 3):
        raise ApiError("ERR_INVALID_CREOSOTE_CLASS")
    glaze_present = opt_bool(b, "glaze_present", False)
    final_cost = sweep_cost(job["inspection_level"], measured, glaze_present, job["trip_zone"])
    job["sweep_final_cost_cents"] = final_cost
    if measured == 3 and job["safety_posture"] in ("PENDING", "SAFE"):
        job["safety_posture"] = "CONDITIONS"
    touch(job)
    log = new_entity("SweepLog", {
        "service_job_id": job["id"],
        "measured_creosote_class": measured,
        "glaze_present": glaze_present,
        "billed_cost_cents": final_cost,
    }, kind=LEAN)
    return ok_object(serialize(log), 201)


@app.route("/service-jobs/<jid>/safety-check", methods=["POST"])
def safety_check_job(jid):
    auth({"Technician"})
    job = get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    b = body_json()
    co_ppm = require_int(b, "co_ppm")
    if co_ppm < 0:
        raise ApiError("ERR_VALIDATION", "co_ppm must be >= 0")
    draft_ok = require(b, "draft_ok")
    if not isinstance(draft_ok, bool):
        raise ApiError("ERR_VALIDATION", "draft_ok must be boolean")
    spillage_detected = opt_bool(b, "spillage_detected", False)

    if co_ppm >= CO_CONDEMN_PPM:
        outcome = "CONDEMN"
    elif co_ppm >= CO_UNSAFE_PPM or spillage_detected:
        outcome = "FAIL"
    elif not draft_ok:
        outcome = "CONDITIONS"
    else:
        outcome = "PASS"

    posture = job["safety_posture"]
    if posture != "CONDEMNED":
        if outcome == "CONDEMN":
            job["safety_posture"] = "CONDEMNED"
        elif outcome == "FAIL":
            job["safety_posture"] = "UNSAFE"
        elif outcome == "CONDITIONS":
            if posture != "UNSAFE":
                job["safety_posture"] = "CONDITIONS"
        elif outcome == "PASS":
            job["safety_posture"] = "SAFE"
    touch(job)

    check = new_entity("SafetyCheck", {
        "service_job_id": job["id"],
        "co_ppm": co_ppm,
        "draft_ok": draft_ok,
        "spillage_detected": spillage_detected,
        "outcome": outcome,
    }, kind=LEAN)
    return ok_object(serialize(check), 201)


@app.route("/service-jobs/<jid>/sweep-logs", methods=["GET"])
def list_sweep_logs(jid):
    auth(ROLES)
    get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    items = [e for e in all_of_type("SweepLog") if e["service_job_id"] == jid]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


@app.route("/service-jobs/<jid>/safety-checks", methods=["GET"])
def list_safety_checks(jid):
    auth(ROLES)
    get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    items = [e for e in all_of_type("SafetyCheck") if e["service_job_id"] == jid]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


def compute_invoice_total(job):
    lines = []
    if job["sweep_final_cost_cents"] is not None:
        lines.append(job["sweep_final_cost_cents"])
    for ro in sorted(all_of_type("RepairOrder"), key=lambda e: e["_seq"]):
        if ro["service_job_id"] == job["id"] and ro["status"] == "COMPLETED":
            lines.append(ro["final_cost_cents"])
    total = 0
    for line in lines:
        fee = round_half_up(Decimal(line) * DISPOSAL_FEE_RATE)
        total += line + fee
    return total


@app.route("/service-jobs/<jid>/complete", methods=["POST"])
def complete_job(jid):
    auth({"BillingClerk"})
    job = get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    if job["job_status"] != "IN_PROGRESS":
        raise ApiError("ERR_JOB_NOT_IN_PROGRESS")
    open_repairs = any(
        ro["service_job_id"] == job["id"]
        and ro["status"] in ("PROPOSED", "APPROVED", "IN_PROGRESS", "BLOCKED")
        for ro in all_of_type("RepairOrder")
    )
    if open_repairs:
        raise ApiError("ERR_JOB_HAS_OPEN_REPAIRS")
    if job["safety_posture"] not in ("SAFE", "CONDITIONS"):
        raise ApiError("ERR_JOB_UNSAFE")

    job["invoice_total_cents"] = compute_invoice_total(job)
    job["job_status"] = "COMPLETED"
    touch(job)

    chimney = DB.get(job["chimney_id"])
    if chimney is not None:
        chimney["last_service_date"] = clock_now()
        touch(chimney)
        for rem in all_of_type("ReminderSchedule"):
            if rem["chimney_id"] == chimney["id"] and rem["status"] == "ACTIVE":
                rem["next_due_date"] = add_months(clock_now(), rem["cadence_months"])
                touch(rem)
    return ok_object(serialize(job))


@app.route("/service-jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    auth({"Dispatcher"})
    job = get_entity(jid, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    if job["job_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_JOB_TERMINAL")

    job["job_status"] = "CANCELLED"
    touch(job)

    # Cascade: appointments -> CANCELLED, release booked minutes
    affected_route_days = set()
    for a in all_of_type("Appointment"):
        if a["service_job_id"] == job["id"] and a["status"] in ("SCHEDULED", "EN_ROUTE", "ON_SITE"):
            a["status"] = "CANCELLED"
            touch(a)
            affected_route_days.add(a["route_day_id"])
    for rid in affected_route_days:
        rd = DB.get(rid)
        if rd is not None:
            recompute_booked(rd)

    # Cascade: open repair orders -> CANCELLED
    for ro in all_of_type("RepairOrder"):
        if ro["service_job_id"] == job["id"] and ro["status"] not in ("COMPLETED", "REJECTED", "CANCELLED"):
            ro["status"] = "CANCELLED"
            touch(ro)
    recompute_committed(job)

    # Cascade: warranties -> VOIDED
    for w in all_of_type("Warranty"):
        if w["service_job_id"] == job["id"] and w["status"] in ("ISSUED", "CLAIMED"):
            w["status"] = "VOIDED"
            touch(w)

    return ok_object(serialize(job))


# =============================================================================
# Appointment
# =============================================================================
APPT_ACTION_ROLES = {
    "DEPART": {"Technician"},
    "ARRIVE": {"Technician"},
    "COMPLETE": {"Technician"},
    "CANCEL": {"Dispatcher"},
    "NO_SHOW": {"Dispatcher"},
}


@app.route("/appointments", methods=["POST"])
def create_appointment():
    auth({"Dispatcher"})
    b = body_json()
    route_day_id = require(b, "route_day_id")
    route_day = get_entity(route_day_id, "RouteDay", "ERR_ROUTE_DAY_NOT_FOUND")
    service_job_id = require(b, "service_job_id")
    job = get_entity(service_job_id, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    technician_id = require(b, "technician_id")
    get_entity(technician_id, "Technician", "ERR_TECHNICIAN_NOT_FOUND")
    start_ts = require_int(b, "start_ts")
    end_ts = require_int(b, "end_ts")

    # Temporal validity
    if end_ts <= start_ts:
        raise ApiError("ERR_INVALID_APPOINTMENT_WINDOW")
    if start_ts < route_day["window_start_ts"] or end_ts > route_day["window_end_ts"]:
        raise ApiError("ERR_APPOINTMENT_OUTSIDE_WINDOW")

    on_site_minutes = (end_ts - start_ts) // 60

    # Scheduling conflicts
    if technician_id != route_day["technician_id"]:
        raise ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED")
    for a in all_of_type("Appointment"):
        if a["technician_id"] != technician_id:
            continue
        if a["status"] in ("CANCELLED", "NO_SHOW"):
            continue
        # conflict unless separated by >= buffer on either side (half-open)
        if not (end_ts + TRAVEL_BUFFER_SECONDS <= a["start_ts"]
                or a["end_ts"] + TRAVEL_BUFFER_SECONDS <= start_ts):
            raise ApiError("ERR_TECHNICIAN_DOUBLE_BOOKED")

    # Fiscal / capacity
    if route_day["booked_minutes"] + on_site_minutes > route_day["capacity_minutes"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED")

    appt = new_entity("Appointment", {
        "route_day_id": route_day_id,
        "service_job_id": service_job_id,
        "technician_id": technician_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "on_site_minutes": on_site_minutes,
        "status": "SCHEDULED",
        "no_show_reason": None,
    })
    recompute_booked(route_day)
    if job["job_status"] == "DRAFT":
        job["job_status"] = "SCHEDULED"
        touch(job)
    return ok_object(serialize(appt), 201)


@app.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    auth(ROLES)
    e = get_entity(aid, "Appointment", "ERR_APPOINTMENT_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/appointments", methods=["GET"])
def list_appointments():
    auth(ROLES)
    items = all_of_type("Appointment")
    for key in ("route_day_id", "service_job_id", "technician_id"):
        val = request.args.get(key)
        if val:
            items = [e for e in items if e[key] == val]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


@app.route("/appointments/<aid>/transitions", methods=["POST"])
def appointment_transition(aid):
    uid, role = auth({"Technician", "Dispatcher"})
    b = body_json()
    action = b.get("action")

    # per-action role (before existence for known actions)
    if action in APPT_ACTION_ROLES and role not in APPT_ACTION_ROLES[action]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")

    appt = get_entity(aid, "Appointment", "ERR_APPOINTMENT_NOT_FOUND")

    # technician identity
    if role == "Technician" and uid != appt["technician_id"]:
        raise ApiError("ERR_TECH_IDENTITY_MISMATCH")

    if action not in APPT_ACTION_ROLES:
        raise ApiError("ERR_VALIDATION", "Unknown action")

    status = appt["status"]
    if action == "DEPART":
        if status != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        appt["status"] = "EN_ROUTE"
        touch(appt)
    elif action == "ARRIVE":
        if status != "EN_ROUTE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        appt["status"] = "ON_SITE"
        touch(appt)
        job = DB.get(appt["service_job_id"])
        if job is not None and job["job_status"] == "SCHEDULED":
            job["job_status"] = "IN_PROGRESS"
            touch(job)
    elif action == "COMPLETE":
        if status != "ON_SITE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        appt["status"] = "COMPLETED"
        touch(appt)
    elif action == "CANCEL":
        if status not in ("SCHEDULED", "EN_ROUTE"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        appt["status"] = "CANCELLED"
        touch(appt)
        rd = DB.get(appt["route_day_id"])
        if rd is not None:
            recompute_booked(rd)
    elif action == "NO_SHOW":
        if status != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        appt["status"] = "NO_SHOW"
        appt["no_show_reason"] = b.get("no_show_reason")
        touch(appt)
        rd = DB.get(appt["route_day_id"])
        if rd is not None:
            recompute_booked(rd)
    return ok_object(serialize(appt))


# =============================================================================
# RepairOrder
# =============================================================================
REPAIR_TYPES = {"CAP", "LINER", "DAMPER", "GAS_LOG_CONVERSION"}
REPAIR_ACTION_ROLES = {
    "APPROVE": {"Dispatcher"},
    "REJECT": {"Dispatcher"},
    "CANCEL": {"Dispatcher"},
    "START": {"Technician"},
    "BLOCK": {"Technician"},
    "RESUME": {"Technician"},
    "COMPLETE": {"Technician"},
}


@app.route("/repair-orders", methods=["POST"])
def create_repair_order():
    auth({"Technician", "Dispatcher"})
    b = body_json()
    service_job_id = require(b, "service_job_id")
    job = get_entity(service_job_id, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    repair_type = require(b, "repair_type")
    if repair_type not in REPAIR_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid repair_type")
    quoted = require_int(b, "quoted_cost_cents")
    if quoted < 0:
        raise ApiError("ERR_VALIDATION", "quoted_cost_cents must be >= 0")

    part_sku = b.get("part_sku")
    if repair_type == "GAS_LOG_CONVERSION":
        part_sku = None
    else:
        if part_sku is None:
            raise ApiError("ERR_PART_REQUIRED")
        if part_sku not in PART_CATALOG[repair_type]:
            raise ApiError("ERR_UNKNOWN_PART")

    if quoted > job["repair_authorization_cents"]:
        raise ApiError("ERR_REPAIR_COST_EXCEEDS_AUTH")

    ro = new_entity("RepairOrder", {
        "service_job_id": service_job_id,
        "repair_type": repair_type,
        "part_sku": part_sku,
        "quoted_cost_cents": quoted,
        "provisional_cost_cents": quoted,
        "final_cost_cents": None,
        "labor_cents": None,
        "parts_cents": None,
        "status": "PROPOSED",
    })
    recompute_committed(job)
    return ok_object(serialize(ro), 201)


@app.route("/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    auth(ROLES)
    e = get_entity(rid, "RepairOrder", "ERR_REPAIR_ORDER_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    auth(ROLES)
    items = all_of_type("RepairOrder")
    job = request.args.get("service_job_id")
    st = request.args.get("status")
    if job:
        items = [e for e in items if e["service_job_id"] == job]
    if st:
        items = [e for e in items if e["status"] == st]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


@app.route("/repair-orders/<rid>/transitions", methods=["POST"])
def repair_transition(rid):
    uid, role = auth({"Technician", "Dispatcher"})
    b = body_json()
    action = b.get("action")

    if action in REPAIR_ACTION_ROLES and role not in REPAIR_ACTION_ROLES[action]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")

    ro = get_entity(rid, "RepairOrder", "ERR_REPAIR_ORDER_NOT_FOUND")

    if action not in REPAIR_ACTION_ROLES:
        raise ApiError("ERR_VALIDATION", "Unknown action")

    job = DB.get(ro["service_job_id"])
    status = ro["status"]

    if action == "APPROVE":
        if status != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        ro["status"] = "APPROVED"
        touch(ro)
    elif action == "REJECT":
        if status != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        ro["status"] = "REJECTED"
        touch(ro)
        if job is not None:
            recompute_committed(job)
    elif action == "START":
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if job is None or job["safety_posture"] not in ("SAFE", "CONDITIONS"):
            raise ApiError("ERR_JOB_UNSAFE")
        ro["status"] = "IN_PROGRESS"
        touch(ro)
    elif action == "BLOCK":
        if status != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        ro["status"] = "BLOCKED"
        touch(ro)
    elif action == "RESUME":
        if status != "BLOCKED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if job is None or job["safety_posture"] not in ("SAFE", "CONDITIONS"):
            raise ApiError("ERR_JOB_UNSAFE")
        ro["status"] = "IN_PROGRESS"
        touch(ro)
    elif action == "COMPLETE":
        final_cost = require_int(b, "final_cost_cents")
        labor = require_int(b, "labor_cents")
        if labor > final_cost:
            raise ApiError("ERR_VALIDATION", "labor_cents must be <= final_cost_cents")
        if status != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        ro["final_cost_cents"] = final_cost
        ro["labor_cents"] = labor
        ro["parts_cents"] = final_cost - labor
        ro["status"] = "COMPLETED"
        touch(ro)
    elif action == "CANCEL":
        if status not in ("PROPOSED", "APPROVED", "IN_PROGRESS", "BLOCKED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        ro["status"] = "CANCELLED"
        touch(ro)
        if job is not None:
            recompute_committed(job)
    return ok_object(serialize(ro))


# =============================================================================
# Warranty
# =============================================================================
COVERAGE_TYPES = {"LABOR_ONLY", "PARTS_INCLUSIVE"}


@app.route("/warranties", methods=["POST"])
def create_warranty():
    auth({"BillingClerk"})
    b = body_json()
    repair_order_id = require(b, "repair_order_id")
    ro = get_entity(repair_order_id, "RepairOrder", "ERR_REPAIR_ORDER_NOT_FOUND")
    service_job_id = require(b, "service_job_id")
    job = get_entity(service_job_id, "ServiceJob", "ERR_SERVICE_JOB_NOT_FOUND")
    if ro["service_job_id"] != service_job_id:
        raise ApiError("ERR_REPAIR_ORDER_NOT_FOUND")
    coverage_type = require(b, "coverage_type")
    if coverage_type not in COVERAGE_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid coverage_type")
    term_months = require_int(b, "term_months")
    if term_months < 1:
        raise ApiError("ERR_VALIDATION", "term_months must be >= 1")

    if ro["status"] != "COMPLETED":
        raise ApiError("ERR_REPAIR_NOT_COMPLETED")

    if job["safety_posture"] not in ("SAFE", "CONDITIONS"):
        raise ApiError("ERR_JOB_UNSAFE")

    w = new_entity("Warranty", {
        "repair_order_id": repair_order_id,
        "service_job_id": service_job_id,
        "coverage_type": coverage_type,
        "term_months": term_months,
        "issued_at": clock_now(),
        "covered_labor_cents": ro["labor_cents"],
        "covered_parts_cents": ro["parts_cents"],
        "status": "ISSUED",
        "claimed_repair_type": None,
        "last_claim_credit_cents": None,
    })
    return ok_object(serialize(w), 201)


@app.route("/warranties/<wid>", methods=["GET"])
def get_warranty(wid):
    auth(ROLES)
    e = get_entity(wid, "Warranty", "ERR_WARRANTY_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/warranties", methods=["GET"])
def list_warranties():
    auth(ROLES)
    items = all_of_type("Warranty")
    ro = request.args.get("repair_order_id")
    job = request.args.get("service_job_id")
    if ro:
        items = [e for e in items if e["repair_order_id"] == ro]
    if job:
        items = [e for e in items if e["service_job_id"] == job]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


@app.route("/warranties/<wid>/file-claim", methods=["POST"])
def file_claim(wid):
    auth({"BillingClerk"})
    w = get_entity(wid, "Warranty", "ERR_WARRANTY_NOT_FOUND")
    b = body_json()
    claimed_repair_type = require(b, "claimed_repair_type")
    if claimed_repair_type not in REPAIR_TYPES:
        raise ApiError("ERR_VALIDATION", "Invalid claimed_repair_type")

    if w["status"] != "ISSUED":
        raise ApiError("ERR_WARRANTY_NOT_CLAIMABLE")

    expiry = add_months(w["issued_at"], w["term_months"])
    if clock_now() > expiry:
        raise ApiError("ERR_WARRANTY_EXPIRED")

    w["claimed_repair_type"] = claimed_repair_type
    labor = w["covered_labor_cents"] or 0
    parts = w["covered_parts_cents"] or 0
    if w["coverage_type"] == "LABOR_ONLY":
        credit = labor
    else:
        elapsed = months_between(w["issued_at"], clock_now())
        term = w["term_months"]
        remaining = Decimal(term - elapsed) / Decimal(term)
        credit = labor + round_half_up(Decimal(parts) * remaining)
    w["last_claim_credit_cents"] = credit
    w["status"] = "CLAIMED"
    touch(w)
    return ok_object(serialize(w))


# =============================================================================
# ReminderSchedule
# =============================================================================
@app.route("/reminder-schedules", methods=["POST"])
def create_reminder():
    auth({"Dispatcher"})
    b = body_json()
    customer_id = require(b, "customer_id")
    get_entity(customer_id, "Customer", "ERR_CUSTOMER_NOT_FOUND")
    chimney_id = require(b, "chimney_id")
    chimney = get_entity(chimney_id, "Chimney", "ERR_CHIMNEY_NOT_FOUND")
    cadence_months = opt_int(b, "cadence_months", 12)
    if cadence_months < 1:
        raise ApiError("ERR_VALIDATION", "cadence_months must be >= 1")
    expected_version = require_int(b, "expected_chimney_version")

    if expected_version != chimney["version"]:
        raise ApiError("ERR_STALE_CHIMNEY_VERSION")

    # Supersede prior ACTIVE reminders for this chimney
    for rem in all_of_type("ReminderSchedule"):
        if rem["chimney_id"] == chimney_id and rem["status"] == "ACTIVE":
            rem["status"] = "DEACTIVATED"
            touch(rem)

    # Superseding act bumps the chimney version
    touch(chimney)

    e = new_entity("ReminderSchedule", {
        "customer_id": customer_id,
        "chimney_id": chimney_id,
        "cadence_months": cadence_months,
        "next_due_date": add_months(clock_now(), cadence_months),
        "status": "ACTIVE",
        "acknowledged_count": 0,
    })
    return ok_object(serialize(e), 201)


@app.route("/reminder-schedules/<sid>", methods=["GET"])
def get_reminder(sid):
    auth(ROLES)
    e = get_entity(sid, "ReminderSchedule", "ERR_REMINDER_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/reminder-schedules", methods=["GET"])
def list_reminders():
    auth(ROLES)
    items = all_of_type("ReminderSchedule")
    cust = request.args.get("customer_id")
    chim = request.args.get("chimney_id")
    st = request.args.get("status")
    if cust:
        items = [e for e in items if e["customer_id"] == cust]
    if chim:
        items = [e for e in items if e["chimney_id"] == chim]
    if st:
        items = [e for e in items if e["status"] == st]
    data, pm = paginate(items, request.args)
    return ok_array(data, pm)


@app.route("/reminder-schedules/<sid>/acknowledge", methods=["POST"])
def acknowledge_reminder(sid):
    auth({"Dispatcher"})
    rem = get_entity(sid, "ReminderSchedule", "ERR_REMINDER_NOT_FOUND")
    if rem["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if clock_now() < rem["next_due_date"]:
        raise ApiError("ERR_REMINDER_NOT_DUE")
    rem["next_due_date"] = add_months(rem["next_due_date"], rem["cadence_months"])
    rem["acknowledged_count"] += 1
    touch(rem)
    return ok_object(serialize(rem))


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ROLES)
    b = body_json()
    to_iso = require(b, "to_iso8601")
    CLOCK["now"] = parse_iso(to_iso)
    return ok_object({})


if __name__ == "__main__":
    import time as _time

    port = int(os.environ.get("PORT", "10000"))
    # The test runner restarts this server before every test by SIGKILL-ing the
    # previous process and *immediately* spawning a new one on the same port,
    # without waiting for the old LISTEN socket to be released by the kernel.
    # A plain bind then races the old process and can raise EADDRINUSE, which
    # would crash boot and be recorded as "server could not be restarted".
    # Retry the bind until the port frees up (well within the runner's window).
    _deadline = _time.time() + 13.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError:
            if _time.time() >= _deadline:
                raise
            _time.sleep(0.25)
