"""
Fertility Preservation & Egg Freezing API — Flask reference implementation.

In-memory storage only (Python dicts keyed by id). No persistence, no seeding.
Fresh empty state on every process boot.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
ALL_ROLES = {"Patient", "Coordinator", "Physician", "Embryologist",
             "BillingAdmin", "PlatformAdmin"}

MIN_MONITORING_VISITS = 3
PROVIDER_BUFFER_MINUTES = 15
OOCYTES_PER_SPECIMEN = 1
STORAGE_PERIOD_DAYS = 365
GRACE_DAYS = 30
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# expected_oocyte_yield
AMH_YIELD_FACTOR = Decimal("2.0")
AFC_YIELD_FACTOR = Decimal("0.5")
MAX_EXPECTED_YIELD = 30
MIN_AMH_NG_ML = Decimal("0.5")

# cycle_cost
BASE_CYCLE_FEE = 800000
MONITORING_VISIT_FEE = 25000
EXPECTED_MONITORING_VISITS = 5
RETRIEVAL_FEE = 400000
MEDICATION_FEE_BY_PROTOCOL = {
    "ANTAGONIST": 300000,
    "LONG_AGONIST": 350000,
    "MINIMAL_STIM": 150000,
}

# storage_renewal_fee
ANNUAL_RATE_PER_SPECIMEN_CENTS = Decimal("4000")
LOYALTY_DISCOUNT_PCT = Decimal("0.0333")

# invoice facility tiers
TIER_LOW_MAX = 500000
TIER_MID_MAX = 1500000
FACILITY_PCT_LOW = Decimal("0.05")
FACILITY_PCT_MID = Decimal("0.03")
FACILITY_PCT_HIGH = Decimal("0.02")

VALID_PROTOCOLS = {"ANTAGONIST", "LONG_AGONIST", "MINIMAL_STIM"}
PROVIDER_ROLES = {"PHYSICIAN", "EMBRYOLOGIST"}
ROOM_KINDS = {"RETRIEVAL_OR", "PROCEDURE"}
SPECIMEN_TYPES = {"VIAL", "STRAW"}
DIRECTIVE_TYPES = {"CONSENT", "DISPOSITION"}
DISPOSITION_ACTIONS = {"THAW_TO_SELF", "DONATE_TO_RESEARCH", "DISCARD", "TRANSFER_TO_PARTNER"}
TRANSFER_TYPES = {"THAW_TO_TRANSFER", "TRANSFER_OUT", "RESEARCH_DONATION"}
SERVICE_TYPES = {"CYCLE", "STORAGE", "RETRIEVAL", "THAW"}
COVERED_SERVICE_TYPES = {"CYCLE", "STORAGE", "RETRIEVAL", "THAW"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "patients": {},
    "providers": {},
    "procedure_rooms": {},
    "storage_tanks": {},
    "consultations": {},
    "stimulation_cycles": {},
    "monitoring_appointments": {},
    "cryo_specimens": {},
    "storage_subscriptions": {},
    "benefit_coverages": {},
    "directives": {},
    "thaw_authorizations": {},
    "invoices": {},
}
_SEQ = {"n": 0}
CLOCK = {"dt": None}


def reset_state():
    for k in DB:
        DB[k] = {}
    _SEQ["n"] = 0
    CLOCK["dt"] = parse_dt(CLOCK_DEFAULT_UTC)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return CLOCK["dt"]


def now_str():
    return fmt_dt(CLOCK["dt"])


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {"api_request_id": _req_id(), "api_request_timestamp": now_str()}


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def object_response(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def list_response(items, limit, offset, total):
    m = _meta()
    m.update({"limit": limit, "offset": offset, "total_count": total,
              "has_more": (offset + limit) < total})
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(HTTPException)
def _handle_http_exception(e):
    if e.code == 404:
        eid = "ERR_NOT_FOUND"
    elif e.code == 405:
        eid = "ERR_NOT_FOUND"
    else:
        eid = "ERR_VALIDATION"
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": eid, "message": str(e)}}
    return jsonify(body), (e.code or 500)


@app.errorhandler(Exception)
def _handle_generic(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized authentication headers")
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Entity / persistence helpers
# ---------------------------------------------------------------------------
def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_entity(extra):
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now_str(),
        "updated_at": now_str(),
        "version": 1,
        "_seq": _next_seq(),
    }
    e.update(extra)
    return e


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_str()


# ---------------------------------------------------------------------------
# Body / schema helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_VALIDATION", 400, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return v


def req_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = body[field]
    if not is_int(v):
        raise err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    return v


def req_num(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = body[field]
    if not is_num(v):
        raise err("ERR_VALIDATION", 400, f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", 400, f"Field {field} must be <= {maximum}")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err("ERR_VALIDATION", 400, f"Field {field} has an invalid value")
    return v


def req_datetime(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", 400, f"Field {field} must be a datetime string")
    try:
        parse_dt(v)
    except Exception:
        raise err("ERR_VALIDATION", 400, f"Field {field} must be a valid ISO 8601 datetime")
    return v


def get_pagination():
    limit = 10
    offset = 0
    lv = request.args.get("limit")
    ov = request.args.get("offset")
    if lv is not None:
        try:
            limit = int(lv)
        except (ValueError, TypeError):
            limit = 10
    if ov is not None:
        try:
            offset = int(ov)
        except (ValueError, TypeError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    items_sorted = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    page = items_sorted[offset:offset + limit]
    return list_response([serialize(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def must_exist(collection, rid):
    e = DB[collection].get(rid)
    if e is None:
        raise err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return e


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_expected_yield(amh_level, afc, age_years):
    base = AMH_YIELD_FACTOR * Decimal(str(amh_level)) + AFC_YIELD_FACTOR * Decimal(int(afc))
    if age_years < 35:
        mult = Decimal("1.00")
    elif age_years < 38:
        mult = Decimal("0.85")
    elif age_years < 41:
        mult = Decimal("0.65")
    else:
        mult = Decimal("0.40")
    raw = base * mult
    val = int(raw.to_integral_value(rounding=ROUND_FLOOR))
    return min(MAX_EXPECTED_YIELD, max(0, val))


def recommend_protocol(expected_yield, eligible):
    """
    AMBIGUITY RESOLUTION (documented choice; PRD leaves boundaries unstated):
    monotonic tier mapping of expected_oocyte_yield -> protocol when ELIGIBLE.
      expected_yield  < 5   -> MINIMAL_STIM   (poor responder)
      5 <= yield      < 15  -> ANTAGONIST     (standard responder)
      yield          >= 15  -> LONG_AGONIST   (high responder)
    INELIGIBLE -> NONE.
    """
    if not eligible:
        return "NONE"
    if expected_yield < 5:
        return "MINIMAL_STIM"
    if expected_yield < 15:
        return "ANTAGONIST"
    return "LONG_AGONIST"


def cycle_cost_estimate(protocol_type):
    med = MEDICATION_FEE_BY_PROTOCOL.get(protocol_type, 0)
    return BASE_CYCLE_FEE + EXPECTED_MONITORING_VISITS * MONITORING_VISIT_FEE + med


def cycle_cost_final(protocol_type, monitoring_visit_count):
    med = MEDICATION_FEE_BY_PROTOCOL.get(protocol_type, 0)
    return (BASE_CYCLE_FEE + monitoring_visit_count * MONITORING_VISIT_FEE
            + med + RETRIEVAL_FEE)


def storage_renewal_fee(specimen_count):
    per_specimen = round_half_up(ANNUAL_RATE_PER_SPECIMEN_CENTS * (Decimal(1) - LOYALTY_DISCOUNT_PCT))
    return specimen_count * per_specimen


def facility_pct(subtotal):
    if subtotal < TIER_LOW_MAX:
        return FACILITY_PCT_LOW
    if subtotal < TIER_MID_MAX:
        return FACILITY_PCT_MID
    return FACILITY_PCT_HIGH


def facility_fee(subtotal):
    return round_half_up(Decimal(subtotal) * facility_pct(subtotal))


def active_coverage_for_patient(patient_id):
    covs = [c for c in DB["benefit_coverages"].values()
            if c["patient_id"] == patient_id and c["status"] == "ACTIVE"]
    if not covs:
        return None
    covs.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return covs[0]


def benefit_applied(subtotal, service_type, coverage):
    if coverage is None:
        return 0, None
    eligible = subtotal if service_type in coverage["covered_service_types"] else 0
    raw_cover = round_half_up(Decimal(str(coverage["covered_pct"])) * Decimal(eligible))
    applied = min(coverage["remaining_cents"], raw_cover)
    return applied, coverage["id"]


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def reconcile_tank(tank_id):
    tank = DB["storage_tanks"].get(tank_id)
    if tank is None:
        return
    used = sum(1 for s in DB["cryo_specimens"].values()
               if s["tank_id"] == tank_id and s["status"] in ("STORED", "RESERVED"))
    full = used >= tank["capacity_slots"]
    if tank["used_slots"] != used or tank["is_full"] != full:
        tank["used_slots"] = used
        tank["is_full"] = full
        touch(tank)


def patient_active_subscription(patient_id):
    for sub in DB["storage_subscriptions"].values():
        if sub["patient_id"] == patient_id and sub["status"] not in ("LAPSED", "CANCELLED"):
            return sub
    return None


def reconcile_subscription(patient_id):
    sub = patient_active_subscription(patient_id)
    if sub is None:
        return
    count = sum(1 for s in DB["cryo_specimens"].values()
                if s["patient_id"] == patient_id and s["status"] in ("STORED", "RESERVED"))
    fee = storage_renewal_fee(count)
    if sub["specimen_count"] != count or sub["annual_fee_cents"] != fee:
        sub["specimen_count"] = count
        sub["annual_fee_cents"] = fee
        touch(sub)


def recompute_monitoring_count(cycle_id):
    return sum(1 for a in DB["monitoring_appointments"].values()
               if a["cycle_id"] == cycle_id and a["visit_status"] != "CANCELLED")


# ===========================================================================
# ROUTES
# ===========================================================================

# ---- Clock ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"PlatformAdmin"})
    body = get_body()
    iso = req_datetime(body, "to_iso8601")
    CLOCK["dt"] = parse_dt(iso)
    return object_response({"current_utc": now_str()}, 200)


# ---- Patient ----
@app.route("/patients", methods=["POST"])
def create_patient():
    authenticate({"Coordinator", "BillingAdmin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    dob = req_datetime(body, "date_of_birth")
    email = req_str(body, "email")
    employer_name = body.get("employer_name")
    if employer_name is not None and not isinstance(employer_name, str):
        raise err("ERR_VALIDATION", 400, "employer_name must be a string")
    e = new_entity({
        "full_name": full_name,
        "date_of_birth": dob,
        "email": email,
        "employer_name": employer_name,
    })
    DB["patients"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    authenticate(ALL_ROLES)
    e = must_exist("patients", pid)
    return object_response(serialize(e), 200)


# ---- Provider ----
@app.route("/providers", methods=["POST"])
def create_provider():
    authenticate({"PlatformAdmin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    provider_role = req_enum(body, "provider_role", PROVIDER_ROLES)
    npi = body.get("npi")
    if npi is not None and not isinstance(npi, str):
        raise err("ERR_VALIDATION", 400, "npi must be a string")
    e = new_entity({"full_name": full_name, "provider_role": provider_role, "npi": npi})
    DB["providers"][e["id"]] = e
    return object_response(serialize(e), 201)


# ---- ProcedureRoom ----
@app.route("/procedure-rooms", methods=["POST"])
def create_room():
    authenticate({"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    room_kind = req_enum(body, "room_kind", ROOM_KINDS)
    e = new_entity({"name": name, "room_kind": room_kind})
    DB["procedure_rooms"][e["id"]] = e
    return object_response(serialize(e), 201)


# ---- StorageTank ----
@app.route("/storage-tanks", methods=["POST"])
def create_tank():
    authenticate({"Embryologist", "PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    capacity = req_int(body, "capacity_slots", minimum=1)
    e = new_entity({
        "name": name,
        "capacity_slots": capacity,
        "used_slots": 0,
        "is_full": False,
    })
    DB["storage_tanks"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/storage-tanks/<tid>", methods=["GET"])
def get_tank(tid):
    authenticate({"Coordinator", "Physician", "Embryologist", "BillingAdmin", "PlatformAdmin"})
    e = must_exist("storage_tanks", tid)
    return object_response(serialize(e), 200)


# ---- Consultation ----
@app.route("/consultations", methods=["POST"])
def create_consultation():
    authenticate({"Coordinator", "Physician"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    age = req_int(body, "patient_age_years", minimum=18)
    amh = req_num(body, "amh_level", minimum=0)
    afc = req_int(body, "antral_follicle_count", minimum=0)
    must_exist("patients", patient_id)
    e = new_entity({
        "patient_id": patient_id,
        "patient_age_years": age,
        "amh_level": amh,
        "antral_follicle_count": afc,
        "expected_oocyte_yield": 0,
        "eligibility_status": "PENDING",
        "recommended_protocol": "NONE",
        "status": "REQUESTED",
    })
    DB["consultations"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/consultations/<cid>", methods=["GET"])
def get_consultation(cid):
    authenticate(ALL_ROLES)
    e = must_exist("consultations", cid)
    return object_response(serialize(e), 200)


@app.route("/consultations", methods=["GET"])
def list_consultations():
    authenticate(ALL_ROLES)
    items = list(DB["consultations"].values())
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [c for c in items if c["patient_id"] == pid]
    return paginate(items)


@app.route("/consultations/<cid>/complete", methods=["POST"])
def complete_consultation(cid):
    authenticate({"Physician"})
    e = must_exist("consultations", cid)
    if e["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", 409, "Consultation is not in REQUESTED state")
    yield_val = compute_expected_yield(e["amh_level"], e["antral_follicle_count"], e["patient_age_years"])
    eligible = Decimal(str(e["amh_level"])) >= MIN_AMH_NG_ML
    e["expected_oocyte_yield"] = yield_val
    e["eligibility_status"] = "ELIGIBLE" if eligible else "INELIGIBLE"
    e["recommended_protocol"] = recommend_protocol(yield_val, eligible)
    e["status"] = "COMPLETED"
    touch(e)
    return object_response(serialize(e), 200)


# ---- StimulationCycle ----
@app.route("/stimulation-cycles", methods=["POST"])
def create_cycle():
    authenticate({"Coordinator"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    consultation_id = req_str(body, "consultation_id")
    must_exist("patients", patient_id)
    must_exist("consultations", consultation_id)
    e = new_entity({
        "patient_id": patient_id,
        "consultation_id": consultation_id,
        "protocol_type": "NONE",
        "monitoring_visit_count": 0,
        "estimated_cost_cents": 0,
        "final_cost_cents": 0,
        "retrieval_room_id": None,
        "retrieval_start": None,
        "retrieval_end": None,
        "oocytes_retrieved": 0,
        "mature_oocyte_count": 0,
        "trigger_at": None,
        "status": "DRAFT",
    })
    DB["stimulation_cycles"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/stimulation-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    authenticate(ALL_ROLES)
    e = must_exist("stimulation_cycles", cid)
    return object_response(serialize(e), 200)


@app.route("/stimulation-cycles", methods=["GET"])
def list_cycles():
    authenticate(ALL_ROLES)
    items = list(DB["stimulation_cycles"].values())
    for f in ("patient_id", "consultation_id", "retrieval_room_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    return paginate(items)


@app.route("/stimulation-cycles/<cid>/schedule", methods=["POST"])
def schedule_cycle(cid):
    authenticate({"Coordinator"})
    cycle = must_exist("stimulation_cycles", cid)
    if cycle["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Cycle is not in DRAFT state")
    consult = DB["consultations"].get(cycle["consultation_id"])
    if consult is None or consult["status"] != "COMPLETED" or consult["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_CONSULTATION_NOT_ELIGIBLE", 422,
                  "Referenced consultation is not COMPLETED and ELIGIBLE")
    cycle["protocol_type"] = consult["recommended_protocol"]
    cycle["estimated_cost_cents"] = cycle_cost_estimate(cycle["protocol_type"])
    cycle["status"] = "SCHEDULED"
    touch(cycle)
    return object_response(serialize(cycle), 200)


@app.route("/stimulation-cycles/<cid>/suspend", methods=["POST"])
def suspend_cycle(cid):
    authenticate({"Physician"})
    cycle = must_exist("stimulation_cycles", cid)
    if cycle["status"] != "MONITORING":
        raise err("ERR_INVALID_STATE", 409, "Cycle is not in MONITORING state")
    cycle["status"] = "SUSPENDED"
    touch(cycle)
    return object_response(serialize(cycle), 200)


@app.route("/stimulation-cycles/<cid>/resume", methods=["POST"])
def resume_cycle(cid):
    authenticate({"Physician"})
    cycle = must_exist("stimulation_cycles", cid)
    if cycle["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", 409, "Cycle is not in SUSPENDED state")
    cycle["status"] = "MONITORING"
    touch(cycle)
    return object_response(serialize(cycle), 200)


@app.route("/stimulation-cycles/<cid>/trigger", methods=["POST"])
def trigger_cycle(cid):
    authenticate({"Physician"})
    cycle = must_exist("stimulation_cycles", cid)
    if cycle["status"] != "MONITORING":
        raise err("ERR_INVALID_STATE", 409, "Cycle is not in MONITORING state")
    if cycle["monitoring_visit_count"] < MIN_MONITORING_VISITS:
        raise err("ERR_INSUFFICIENT_MONITORING_VISITS", 422,
                  "Cycle has insufficient monitoring visits to trigger")
    cycle["trigger_at"] = now_str()
    cycle["status"] = "TRIGGERED"
    touch(cycle)
    return object_response(serialize(cycle), 200)


def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@app.route("/stimulation-cycles/<cid>/retrieve", methods=["POST"])
def retrieve_cycle(cid):
    authenticate({"Physician"})
    body = get_body()
    room_id = req_str(body, "retrieval_room_id")
    r_start = req_datetime(body, "retrieval_start")
    r_end = req_datetime(body, "retrieval_end")
    oocytes = req_int(body, "oocytes_retrieved", minimum=0)
    mature = req_int(body, "mature_oocyte_count", minimum=0)
    tank_id = req_str(body, "tank_id")
    specimen_type = req_enum(body, "specimen_type", SPECIMEN_TYPES)

    # existence: path cycle -> room -> tank (left to right)
    cycle = must_exist("stimulation_cycles", cid)
    room = must_exist("procedure_rooms", room_id)
    tank = must_exist("storage_tanks", tank_id)

    # state
    if cycle["status"] != "TRIGGERED":
        raise err("ERR_INVALID_STATE", 409, "Cycle is not in TRIGGERED state")

    # room availability (priority 14) — half-open, no buffer
    ns, ne = parse_dt(r_start), parse_dt(r_end)
    for other in DB["stimulation_cycles"].values():
        if other["id"] == cid:
            continue
        if other.get("retrieval_room_id") == room_id and other.get("retrieval_start") and other.get("retrieval_end"):
            os_, oe = parse_dt(other["retrieval_start"]), parse_dt(other["retrieval_end"])
            if _intervals_overlap_halfopen(ns, ne, os_, oe):
                raise err("ERR_ROOM_UNAVAILABLE", 409, "Retrieval window overlaps another on this room")

    # tank capacity (priority 16)
    if tank["used_slots"] + mature > tank["capacity_slots"]:
        raise err("ERR_TANK_AT_CAPACITY", 409, "Storing specimens would exceed tank capacity")

    # commit
    cycle["retrieval_room_id"] = room_id
    cycle["retrieval_start"] = r_start
    cycle["retrieval_end"] = r_end
    cycle["oocytes_retrieved"] = oocytes
    cycle["mature_oocyte_count"] = mature

    for _ in range(mature):
        sp = new_entity({
            "patient_id": cycle["patient_id"],
            "cycle_id": cycle["id"],
            "tank_id": tank_id,
            "specimen_type": specimen_type,
            "oocyte_count": OOCYTES_PER_SPECIMEN,
            "status": "STORED",
        })
        DB["cryo_specimens"][sp["id"]] = sp

    reconcile_tank(tank_id)
    reconcile_subscription(cycle["patient_id"])

    cycle["final_cost_cents"] = cycle_cost_final(cycle["protocol_type"], cycle["monitoring_visit_count"])
    cycle["status"] = "COMPLETED"
    touch(cycle)
    return object_response(serialize(cycle), 200)


@app.route("/stimulation-cycles/<cid>/cancel", methods=["POST"])
def cancel_cycle(cid):
    authenticate({"Coordinator"})
    cycle = must_exist("stimulation_cycles", cid)
    if cycle["status"] not in ("DRAFT", "SCHEDULED", "MONITORING", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", 409, "Cycle is not in a cancellable state")
    for a in DB["monitoring_appointments"].values():
        if a["cycle_id"] == cid and a["visit_status"] == "SCHEDULED":
            a["visit_status"] = "CANCELLED"
            touch(a)
    cycle["monitoring_visit_count"] = recompute_monitoring_count(cid)
    cycle["status"] = "CANCELLED"
    touch(cycle)
    return object_response(serialize(cycle), 200)


# ---- MonitoringAppointment ----
@app.route("/monitoring-appointments", methods=["POST"])
def create_appointment():
    authenticate({"Coordinator"})
    body = get_body()
    cycle_id = req_str(body, "cycle_id")
    provider_id = req_str(body, "provider_id")
    s_start = req_datetime(body, "scheduled_start")
    s_end = req_datetime(body, "scheduled_end")
    if parse_dt(s_end) <= parse_dt(s_start):
        raise err("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")

    cycle = must_exist("stimulation_cycles", cycle_id)
    must_exist("providers", provider_id)

    if cycle["status"] not in ("SCHEDULED", "MONITORING"):
        raise err("ERR_INVALID_STATE", 409, "Cycle is not accepting monitoring appointments")

    # provider buffered overlap (priority 13)
    ns, ne = parse_dt(s_start), parse_dt(s_end)
    buf = timedelta(minutes=PROVIDER_BUFFER_MINUTES)
    for a in DB["monitoring_appointments"].values():
        if a["provider_id"] == provider_id and a["visit_status"] != "CANCELLED":
            es, ee = parse_dt(a["scheduled_start"]), parse_dt(a["scheduled_end"])
            if ns < ee + buf and es - buf < ne:
                raise err("ERR_PROVIDER_UNAVAILABLE", 409,
                          "Appointment overlaps provider's buffered availability")

    e = new_entity({
        "cycle_id": cycle_id,
        "provider_id": provider_id,
        "scheduled_start": s_start,
        "scheduled_end": s_end,
        "visit_status": "SCHEDULED",
    })
    DB["monitoring_appointments"][e["id"]] = e

    if cycle["status"] == "SCHEDULED":
        cycle["status"] = "MONITORING"
    cycle["monitoring_visit_count"] = recompute_monitoring_count(cycle_id)
    touch(cycle)
    return object_response(serialize(e), 201)


@app.route("/monitoring-appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    authenticate(ALL_ROLES)
    e = must_exist("monitoring_appointments", aid)
    return object_response(serialize(e), 200)


@app.route("/monitoring-appointments", methods=["GET"])
def list_appointments():
    authenticate(ALL_ROLES)
    items = list(DB["monitoring_appointments"].values())
    for f in ("cycle_id", "provider_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    return paginate(items)


# ---- CryoSpecimen (read-only) ----
@app.route("/cryo-specimens/<sid>", methods=["GET"])
def get_specimen(sid):
    authenticate(ALL_ROLES)
    e = must_exist("cryo_specimens", sid)
    return object_response(serialize(e), 200)


@app.route("/cryo-specimens", methods=["GET"])
def list_specimens():
    authenticate(ALL_ROLES)
    items = list(DB["cryo_specimens"].values())
    for f in ("patient_id", "cycle_id", "tank_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    return paginate(items)


# ---- StorageSubscription ----
@app.route("/storage-subscriptions", methods=["POST"])
def create_subscription():
    authenticate({"BillingAdmin"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    must_exist("patients", patient_id)
    if patient_active_subscription(patient_id) is not None:
        raise err("ERR_DUPLICATE_ACTIVE_RESOURCE", 409,
                  "Patient already has a non-terminal storage subscription")
    e = new_entity({
        "patient_id": patient_id,
        "specimen_count": 0,
        "annual_fee_cents": 0,
        "current_period_start": None,
        "current_period_end": None,
        "last_paid_at": None,
        "status": "PENDING_ACTIVATION",
    })
    DB["storage_subscriptions"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/storage-subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    authenticate(ALL_ROLES)
    e = must_exist("storage_subscriptions", sid)
    return object_response(serialize(e), 200)


@app.route("/storage-subscriptions", methods=["GET"])
def list_subscriptions():
    authenticate(ALL_ROLES)
    items = list(DB["storage_subscriptions"].values())
    v = request.args.get("patient_id")
    if v is not None:
        items = [s for s in items if s["patient_id"] == v]
    return paginate(items)


@app.route("/storage-subscriptions/<sid>/record-payment", methods=["POST"])
def record_payment(sid):
    authenticate({"BillingAdmin"})
    sub = must_exist("storage_subscriptions", sid)
    now = now_dt()
    if sub["status"] == "PENDING_ACTIVATION":
        start = now
        sub["current_period_start"] = fmt_dt(start)
        sub["current_period_end"] = fmt_dt(start + timedelta(days=STORAGE_PERIOD_DAYS))
        sub["last_paid_at"] = now_str()
        sub["status"] = "ACTIVE"
        touch(sub)
    elif sub["status"] == "PAST_DUE":
        period_end = parse_dt(sub["current_period_end"])
        if now >= period_end + timedelta(days=GRACE_DAYS):
            raise err("ERR_INVALID_STATE", 409,
                      "Grace window has elapsed; payment can no longer reactivate")
        new_start = period_end
        sub["current_period_start"] = fmt_dt(new_start)
        sub["current_period_end"] = fmt_dt(new_start + timedelta(days=STORAGE_PERIOD_DAYS))
        sub["last_paid_at"] = now_str()
        sub["status"] = "ACTIVE"
        touch(sub)
    else:
        raise err("ERR_INVALID_STATE", 409, "Subscription is not awaiting a payment")
    return object_response(serialize(sub), 200)


@app.route("/storage-subscriptions/<sid>/renew", methods=["POST"])
def renew_subscription(sid):
    authenticate({"BillingAdmin"})
    sub = must_exist("storage_subscriptions", sid)
    now = now_dt()
    if sub["status"] == "ACTIVE":
        period_end = parse_dt(sub["current_period_end"])
        if now < period_end:
            raise err("ERR_PERIOD_NOT_ELAPSED", 409, "Billing period has not yet elapsed")
        sub["annual_fee_cents"] = storage_renewal_fee(sub["specimen_count"])
        sub["status"] = "PAST_DUE"
        touch(sub)
    elif sub["status"] == "PAST_DUE":
        period_end = parse_dt(sub["current_period_end"])
        if now < period_end + timedelta(days=GRACE_DAYS):
            raise err("ERR_INVALID_STATE", 409, "Grace window has not yet elapsed")
        # lapse: discard the patient's STORED specimens
        affected_tanks = set()
        for s in DB["cryo_specimens"].values():
            if s["patient_id"] == sub["patient_id"] and s["status"] == "STORED":
                s["status"] = "DISCARDED"
                touch(s)
                affected_tanks.add(s["tank_id"])
        sub["status"] = "LAPSED"
        touch(sub)
        for tid in affected_tanks:
            reconcile_tank(tid)
    else:
        raise err("ERR_INVALID_STATE", 409, "Subscription cannot be renewed from its current state")
    return object_response(serialize(sub), 200)


@app.route("/storage-subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    authenticate({"BillingAdmin"})
    sub = must_exist("storage_subscriptions", sid)
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", 409, "Subscription is not in a cancellable state")
    sub["status"] = "CANCELLED"
    touch(sub)
    return object_response(serialize(sub), 200)


# ---- BenefitCoverage ----
@app.route("/benefit-coverages", methods=["POST"])
def create_coverage():
    authenticate({"BillingAdmin"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    employer_name = req_str(body, "employer_name")
    annual_cap = req_int(body, "annual_cap_cents", minimum=0)
    covered_pct = req_num(body, "covered_pct", minimum=0, maximum=1)
    if "covered_service_types" not in body or body["covered_service_types"] is None:
        raise err("ERR_VALIDATION", 400, "Missing required field: covered_service_types")
    cst = body["covered_service_types"]
    if not isinstance(cst, list):
        raise err("ERR_VALIDATION", 400, "covered_service_types must be an array")
    for item in cst:
        if not isinstance(item, str) or item not in COVERED_SERVICE_TYPES:
            raise err("ERR_VALIDATION", 400, "covered_service_types has an invalid value")
    must_exist("patients", patient_id)
    if active_coverage_for_patient(patient_id) is not None:
        raise err("ERR_DUPLICATE_ACTIVE_RESOURCE", 409,
                  "Patient already has an ACTIVE benefit coverage")
    e = new_entity({
        "patient_id": patient_id,
        "employer_name": employer_name,
        "annual_cap_cents": annual_cap,
        "covered_pct": covered_pct,
        "covered_service_types": list(cst),
        "consumed_cents": 0,
        "remaining_cents": annual_cap,
        "status": "ACTIVE",
    })
    DB["benefit_coverages"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/benefit-coverages/<bid>", methods=["GET"])
def get_coverage(bid):
    authenticate(ALL_ROLES)
    e = must_exist("benefit_coverages", bid)
    return object_response(serialize(e), 200)


@app.route("/benefit-coverages", methods=["GET"])
def list_coverages():
    authenticate(ALL_ROLES)
    items = list(DB["benefit_coverages"].values())
    v = request.args.get("patient_id")
    if v is not None:
        items = [c for c in items if c["patient_id"] == v]
    return paginate(items)


# ---- Directive ----
@app.route("/directives", methods=["POST"])
def create_directive():
    authenticate({"Patient"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    directive_type = req_enum(body, "directive_type", DIRECTIVE_TYPES)
    disposition_action = None
    if directive_type == "DISPOSITION":
        disposition_action = req_enum(body, "disposition_action", DISPOSITION_ACTIONS)
    else:
        if body.get("disposition_action") is not None:
            da = body["disposition_action"]
            if not isinstance(da, str) or da not in DISPOSITION_ACTIONS:
                raise err("ERR_VALIDATION", 400, "disposition_action has an invalid value")
            disposition_action = da
    expected_version = req_int(body, "expected_patient_version")

    # existence (priority 4)
    patient = must_exist("patients", patient_id)

    # OCC (priority 6)
    if expected_version != patient["version"]:
        raise err("ERR_STALE_VERSION", 412, "expected_patient_version does not match patient version")

    # supersede prior ACTIVE same-type directive
    for d in DB["directives"].values():
        if (d["patient_id"] == patient_id and d["directive_type"] == directive_type
                and d["status"] == "ACTIVE"):
            d["status"] = "SUPERSEDED"
            touch(d)

    e = new_entity({
        "patient_id": patient_id,
        "directive_type": directive_type,
        "disposition_action": disposition_action,
        "signed_at": now_str(),
        "status": "ACTIVE",
    })
    DB["directives"][e["id"]] = e

    # every create bumps the patient version by exactly 1
    touch(patient)

    return object_response(serialize(e), 201)


@app.route("/directives/<did>", methods=["GET"])
def get_directive(did):
    authenticate(ALL_ROLES)
    e = must_exist("directives", did)
    return object_response(serialize(e), 200)


@app.route("/directives", methods=["GET"])
def list_directives():
    authenticate(ALL_ROLES)
    items = list(DB["directives"].values())
    for f in ("patient_id", "directive_type"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if d[f] == v]
    return paginate(items)


@app.route("/directives/<did>/revoke", methods=["POST"])
def revoke_directive(did):
    uid, _role = authenticate({"Patient"})
    d = must_exist("directives", did)
    if d["patient_id"] != uid:
        raise err("ERR_UNAUTHORIZED", 403, "Only the owning patient may revoke this directive")
    if d["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "Directive is not ACTIVE")
    d["status"] = "REVOKED"
    touch(d)
    return object_response(serialize(d), 200)


# ---- ThawTransferAuthorization ----
@app.route("/thaw-transfer-authorizations", methods=["POST"])
def create_thaw():
    uid, _role = authenticate({"Physician"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    if "specimen_ids" not in body or body["specimen_ids"] is None:
        raise err("ERR_VALIDATION", 400, "Missing required field: specimen_ids")
    specimen_ids = body["specimen_ids"]
    if not isinstance(specimen_ids, list) or not all(isinstance(x, str) for x in specimen_ids):
        raise err("ERR_VALIDATION", 400, "specimen_ids must be an array of strings")
    transfer_type = req_enum(body, "transfer_type", TRANSFER_TYPES)

    # existence: patient then each specimen (left-to-right)
    must_exist("patients", patient_id)
    for sid in specimen_ids:
        must_exist("cryo_specimens", sid)

    e = new_entity({
        "patient_id": patient_id,
        "specimen_ids": list(specimen_ids),
        "transfer_type": transfer_type,
        "requester_provider_id": uid,
        "authorizer_provider_id": None,
        "consent_directive_id": None,
        "disposition_directive_id": None,
        "status": "REQUESTED",
    })
    DB["thaw_authorizations"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/thaw-transfer-authorizations/<tid>", methods=["GET"])
def get_thaw(tid):
    authenticate(ALL_ROLES)
    e = must_exist("thaw_authorizations", tid)
    return object_response(serialize(e), 200)


@app.route("/thaw-transfer-authorizations", methods=["GET"])
def list_thaw():
    authenticate(ALL_ROLES)
    items = list(DB["thaw_authorizations"].values())
    v = request.args.get("patient_id")
    if v is not None:
        items = [a for a in items if a["patient_id"] == v]
    return paginate(items)


def _active_directive(patient_id, directive_type):
    for d in DB["directives"].values():
        if (d["patient_id"] == patient_id and d["directive_type"] == directive_type
                and d["status"] == "ACTIVE"):
            return d
    return None


@app.route("/thaw-transfer-authorizations/<tid>/authorize", methods=["POST"])
def authorize_thaw(tid):
    uid, _role = authenticate({"Physician"})
    auth = must_exist("thaw_authorizations", tid)

    # state (priority 5)
    if auth["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", 409, "Authorization is not in REQUESTED state")

    # consent (8) / disposition (9)
    consent = _active_directive(auth["patient_id"], "CONSENT")
    if consent is None:
        raise err("ERR_CONSENT_NOT_ACTIVE", 422, "Patient lacks an ACTIVE CONSENT directive")
    disposition = _active_directive(auth["patient_id"], "DISPOSITION")
    if disposition is None:
        raise err("ERR_DISPOSITION_NOT_ACTIVE", 422, "Patient lacks an ACTIVE DISPOSITION directive")

    # segregation of duties (10)
    if uid == auth["requester_provider_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 409,
                  "Authorizer must differ from the requester")

    # specimen ownership (11)
    specimens = []
    for sid in auth["specimen_ids"]:
        sp = DB["cryo_specimens"].get(sid)
        if sp is None or sp["patient_id"] != auth["patient_id"]:
            raise err("ERR_SPECIMEN_NOT_OWNED", 422,
                      "A specimen does not belong to the authorization's patient")
        specimens.append(sp)

    # specimen availability (12): must be STORED
    for sp in specimens:
        if sp["status"] != "STORED":
            raise err("ERR_SPECIMEN_NOT_AVAILABLE", 409, "A specimen is not in STORED status")

    # commit
    auth["consent_directive_id"] = consent["id"]
    auth["disposition_directive_id"] = disposition["id"]
    auth["authorizer_provider_id"] = uid
    for sp in specimens:
        sp["status"] = "RESERVED"
        touch(sp)
    # reserved specimens still occupy their slots; used_slots unchanged
    auth["status"] = "AUTHORIZED"
    touch(auth)
    return object_response(serialize(auth), 200)


@app.route("/thaw-transfer-authorizations/<tid>/deny", methods=["POST"])
def deny_thaw(tid):
    authenticate({"Physician"})
    auth = must_exist("thaw_authorizations", tid)
    if auth["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", 409, "Authorization is not in REQUESTED state")
    auth["status"] = "DENIED"
    touch(auth)
    return object_response(serialize(auth), 200)


@app.route("/thaw-transfer-authorizations/<tid>/execute", methods=["POST"])
def execute_thaw(tid):
    authenticate({"Embryologist"})
    auth = must_exist("thaw_authorizations", tid)
    if auth["status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", 409, "Authorization is not in AUTHORIZED state")

    specimens = []
    for sid in auth["specimen_ids"]:
        sp = DB["cryo_specimens"].get(sid)
        if sp is None or sp["status"] != "RESERVED":
            raise err("ERR_SPECIMEN_NOT_AVAILABLE", 409, "A specimen is not in RESERVED status")
        specimens.append(sp)

    affected_tanks = set()
    for sp in specimens:
        sp["status"] = "THAWED"
        touch(sp)
        affected_tanks.add(sp["tank_id"])
    for t in affected_tanks:
        reconcile_tank(t)
    reconcile_subscription(auth["patient_id"])

    auth["status"] = "EXECUTED"
    touch(auth)
    return object_response(serialize(auth), 200)


# ---- Invoice ----
def _validate_line_items(body):
    if "line_items" not in body or body["line_items"] is None:
        raise err("ERR_VALIDATION", 400, "Missing required field: line_items")
    items = body["line_items"]
    if not isinstance(items, list):
        raise err("ERR_VALIDATION", 400, "line_items must be an array")
    normalized = []
    for it in items:
        if not isinstance(it, dict):
            raise err("ERR_VALIDATION", 400, "line_items entries must be objects")
        desc = it.get("description")
        if not isinstance(desc, str):
            raise err("ERR_VALIDATION", 400, "line_items[].description must be a string")
        amt = it.get("amount_cents")
        if not is_int(amt) or amt < 0:
            raise err("ERR_VALIDATION", 400, "line_items[].amount_cents must be a non-negative integer")
        normalized.append({"description": desc, "amount_cents": amt})
    return normalized


@app.route("/invoices", methods=["POST"])
def create_invoice():
    authenticate({"BillingAdmin"})
    body = get_body()
    patient_id = req_str(body, "patient_id")
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    line_items = _validate_line_items(body)
    must_exist("patients", patient_id)

    subtotal = sum(li["amount_cents"] for li in line_items)
    fee = facility_fee(subtotal)
    coverage = active_coverage_for_patient(patient_id)
    est_cover, _cov_id = benefit_applied(subtotal, service_type, coverage)
    total_due = subtotal + fee - est_cover

    e = new_entity({
        "patient_id": patient_id,
        "service_type": service_type,
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "facility_fee_cents": fee,
        "estimated_coverage_cents": est_cover,
        "settled_coverage_cents": 0,
        "total_due_cents": total_due,
        "status": "DRAFT",
        "_settled_coverage_id": None,
    })
    DB["invoices"][e["id"]] = e
    return object_response(serialize(e), 201)


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    authenticate(ALL_ROLES)
    e = must_exist("invoices", iid)
    return object_response(serialize(e), 200)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    authenticate(ALL_ROLES)
    items = list(DB["invoices"].values())
    v = request.args.get("patient_id")
    if v is not None:
        items = [i for i in items if i["patient_id"] == v]
    return paginate(items)


@app.route("/invoices/<iid>/finalize", methods=["POST"])
def finalize_invoice(iid):
    authenticate({"BillingAdmin"})
    inv = must_exist("invoices", iid)
    if inv["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Invoice is not in DRAFT state")

    subtotal = sum(li["amount_cents"] for li in inv["line_items"])
    fee = facility_fee(subtotal)
    coverage = active_coverage_for_patient(inv["patient_id"])
    settled, cov_id = benefit_applied(subtotal, inv["service_type"], coverage)

    inv["subtotal_cents"] = subtotal
    inv["facility_fee_cents"] = fee
    inv["settled_coverage_cents"] = settled
    inv["total_due_cents"] = subtotal + fee - settled
    inv["_settled_coverage_id"] = cov_id if settled > 0 else None
    inv["status"] = "FINALIZED"
    touch(inv)

    if settled > 0 and cov_id is not None:
        cov = DB["benefit_coverages"].get(cov_id)
        if cov is not None:
            cov["consumed_cents"] += settled
            cov["remaining_cents"] = cov["annual_cap_cents"] - cov["consumed_cents"]
            if cov["remaining_cents"] == 0:
                cov["status"] = "EXHAUSTED"
            touch(cov)

    return object_response(serialize(inv), 200)


@app.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    authenticate({"BillingAdmin"})
    inv = must_exist("invoices", iid)
    if inv["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", 409, "Invoice is not in FINALIZED state")

    settled = inv["settled_coverage_cents"]
    cov_id = inv.get("_settled_coverage_id")
    inv["status"] = "VOID"
    touch(inv)

    if settled > 0 and cov_id is not None:
        cov = DB["benefit_coverages"].get(cov_id)
        if cov is not None:
            cov["consumed_cents"] -= settled
            cov["remaining_cents"] = cov["annual_cap_cents"] - cov["consumed_cents"]
            if cov["status"] == "EXHAUSTED" and cov["remaining_cents"] > 0:
                cov["status"] = "ACTIVE"
            touch(cov)

    return object_response(serialize(inv), 200)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
