"""
McKinney-Vento School Transport API — Python + Flask reference implementation.

Single-file, in-memory. The store starts EMPTY on every boot; every entity is
created through the declared API surface. Nothing is seeded at startup.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PER_MILE_RATE_CENTS = 155
BASE_TRIP_CENTS = 500
SCHOOL_DAYS_PER_MONTH = 20
SHARE_CAP_CENTS = 100000
DEFAULT_MAX_CASELOAD = 25
VEHICLE_BUFFER_MINUTES = 30
DISTRICT_CONCURRENT_TRIP_CAP = 3

ROLES = {"StateCoordinator", "Liaison", "TransportCoordinator", "Registrar"}
ALL_ROLES = ["StateCoordinator", "TransportCoordinator", "Liaison", "Registrar"]

LIVING_SITUATIONS = {"SHELTER", "UNSHELTERED", "HOTEL_MOTEL", "DOUBLED_UP",
                     "FOSTER_PLACEMENT", "HOUSED"}
SELF_CATEGORIES = {"HOMELESS", "FOSTER", "NONE"}
DET_CATEGORIES = {"HOMELESS", "FOSTER"}
DET_BASES = {"NIGHT_TO_NIGHT", "SHELTER", "HOTEL_MOTEL", "DOUBLED_UP",
             "UNSHELTERED", "FOSTER"}
DET_DECISIONS = {"ELIGIBLE", "INELIGIBLE"}
VEHICLE_STATUSES = {"IN_SERVICE", "OUT_OF_SERVICE", "RETIRED"}
DISPUTE_TYPES = {"ELIGIBILITY", "ENROLLMENT", "TRANSPORT"}
DISPUTE_OUTCOMES = {"UPHELD", "DENIED"}
REFERRAL_SUBJECTS = {"MATH", "READING", "OTHER"}

LIVING_WEIGHT = {"SHELTER": 40, "UNSHELTERED": 50, "HOTEL_MOTEL": 30,
                 "DOUBLED_UP": 20, "FOSTER_PLACEMENT": 35, "HOUSED": 0}
BASIS_WEIGHT = {"NIGHT_TO_NIGHT": 50, "SHELTER": 40, "HOTEL_MOTEL": 30,
                "DOUBLED_UP": 20, "UNSHELTERED": 50, "FOSTER": 35}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "districts": {},
    "liaisons": {},
    "students": {},
    "determinations": {},
    "plans": {},
    "vehicles": {},
    "trips": {},
    "agreements": {},
    "ledger_entries": {},
    "benefit_links": {},
    "disputes": {},
    "referrals": {},
}
_SEQ = {"n": 0}

# Logical clock -------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}


def now_dt():
    return CLOCK["now"]


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "districts": "ERR_DISTRICT_NOT_FOUND",
    "liaisons": "ERR_LIAISON_NOT_FOUND",
    "students": "ERR_STUDENT_NOT_FOUND",
    "determinations": "ERR_DETERMINATION_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "vehicles": "ERR_VEHICLE_NOT_FOUND",
    "trips": "ERR_TRIP_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "benefit_links": "ERR_BENEFIT_LINK_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "referrals": "ERR_REFERRAL_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
}


def resolve(kind, ident):
    rec = DB[kind].get(ident)
    if rec is None:
        raise ApiError(NOT_FOUND[kind], 404, f"{kind[:-1]} {ident} not found")
    return rec


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_ts(now_dt())}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta_extra = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}
    return ok(items, status=200, response_type="array", meta_extra=meta_extra)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid credentials")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")
    g.role = role
    g.uid = uid
    return role


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a non-empty string")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_nonneg_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a non-negative integer")
    return v


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} is not a valid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_record(common=True):
    ts = fmt_ts(now_dt())
    rec = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = fmt_ts(now_dt())
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def paginate_and_serialize(records, limit, offset):
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    return [serialize(r) for r in page], total


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def serving_delta(trip_cost_cents, serving_pct):
    return round_half_up(Decimal(trip_cost_cents) * Decimal(str(serving_pct)))


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def recompute_caseload(liaison):
    if liaison is None:
        return
    count = 0
    for s in DB["students"].values():
        if (s.get("liaison_id") == liaison["id"]
                and s["status"] != "WITHDRAWN"
                and s["eligibility_status"] == "ELIGIBLE"):
            count += 1
    if liaison["current_caseload"] != count:
        liaison["current_caseload"] = count
        touch(liaison)


def student_active_benefit_links(student_id):
    return [b for b in DB["benefit_links"].values()
            if b["student_id"] == student_id and b["status"] == "ACTIVE"]


def create_benefit_link(student):
    district_id = student["enrolled_district_id"]
    bl = new_record(common=True)
    bl.update({
        "student_id": student["id"],
        "district_id": district_id,
        "source": "AUTO_ELIGIBILITY",
        "status": "ACTIVE",
    })
    DB["benefit_links"][bl["id"]] = bl
    district = DB["districts"].get(district_id)
    if district is not None:
        district["categorical_eligible_count"] += 1
        touch(district)
    return bl


def latest_agreement_for_plan(plan_id):
    ags = [a for a in DB["agreements"].values()
           if a["transportation_plan_id"] == plan_id]
    if not ags:
        return None
    return max(ags, key=lambda a: a["_seq"])


def compute_priority_final(determination):
    score = BASIS_WEIGHT[determination["basis"]]
    if determination["category"] == "FOSTER":
        score += 10
    return score


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["StateCoordinator"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    CLOCK["now"] = dt
    return ok({"current_utc": fmt_ts(dt)})


# ---------------------------------------------------------------------------
# District
# ---------------------------------------------------------------------------
@app.route("/mv/districts", methods=["POST"])
def create_district():
    require_auth(["StateCoordinator"])
    body = get_body()
    require_fields(body, ["name", "nces_code", "transport_budget_cents"])
    name = require_str(body, "name")
    nces = require_str(body, "nces_code")
    budget = require_nonneg_int(body, "transport_budget_cents")
    rec = new_record(common=True)
    rec.update({
        "name": name,
        "nces_code": nces,
        "transport_budget_cents": budget,
        "committed_cost_cents": 0,
        "transport_balance_cents": 0,
        "categorical_eligible_count": 0,
    })
    DB["districts"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/districts/<district_id>", methods=["GET"])
def get_district(district_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("districts", district_id)))


# ---------------------------------------------------------------------------
# Liaison
# ---------------------------------------------------------------------------
@app.route("/mv/liaisons", methods=["POST"])
def create_liaison():
    require_auth(["StateCoordinator"])
    body = get_body()
    require_fields(body, ["district_id", "full_name", "email"])
    district_id = require_str(body, "district_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    max_caseload = DEFAULT_MAX_CASELOAD
    if "max_caseload" in body and body["max_caseload"] is not None:
        max_caseload = require_nonneg_int(body, "max_caseload")
    resolve("districts", district_id)
    rec = new_record(common=True)
    rec.update({
        "district_id": district_id,
        "full_name": full_name,
        "email": email,
        "max_caseload": max_caseload,
        "current_caseload": 0,
    })
    DB["liaisons"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/liaisons/<liaison_id>", methods=["GET"])
def get_liaison(liaison_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("liaisons", liaison_id)))


@app.route("/mv/liaisons", methods=["GET"])
def list_liaisons():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["liaisons"].values())
    district_id = request.args.get("district_id")
    if district_id:
        recs = [r for r in recs if r["district_id"] == district_id]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
@app.route("/mv/students", methods=["POST"])
def create_student():
    require_auth(["Registrar", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["first_name", "last_name", "birthdate",
                          "enrolled_district_id", "origin_district_id",
                          "living_situation"])
    first = require_str(body, "first_name")
    last = require_str(body, "last_name")
    birthdate = require_str(body, "birthdate")
    enrolled = require_str(body, "enrolled_district_id")
    origin = require_str(body, "origin_district_id")
    living = require_enum(body, "living_situation", LIVING_SITUATIONS)
    self_cat = "NONE"
    if "self_declared_category" in body and body["self_declared_category"] is not None:
        self_cat = require_enum(body, "self_declared_category", SELF_CATEGORIES)
    records_received = False
    if "records_received" in body and body["records_received"] is not None:
        if not isinstance(body["records_received"], bool):
            raise ApiError("ERR_VALIDATION", 422, "records_received must be boolean")
        records_received = body["records_received"]
    # existence (left to right)
    resolve("districts", enrolled)
    resolve("districts", origin)
    rec = new_record(common=True)
    rec.update({
        "first_name": first,
        "last_name": last,
        "birthdate": birthdate,
        "enrolled_district_id": enrolled,
        "origin_district_id": origin,
        "liaison_id": None,
        "living_situation": living,
        "self_declared_category": self_cat,
        "records_received": records_received,
        "status": "INTAKE",
        "eligibility_status": "UNDETERMINED",
        "priority_score": LIVING_WEIGHT[living],
        "priority_basis": "PROVISIONAL",
    })
    DB["students"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/students/<student_id>", methods=["GET"])
def get_student(student_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("students", student_id)))


@app.route("/mv/students", methods=["GET"])
def list_students():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["students"].values())
    for key in ("enrolled_district_id", "origin_district_id", "liaison_id"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/students/<student_id>/enroll", methods=["POST"])
def enroll_student(student_id):
    require_auth(["Registrar", "StateCoordinator"])
    student = resolve("students", student_id)
    if student["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE", 409, "Student not in INTAKE state")
    student["status"] = "ENROLLED"
    touch(student)
    return ok(serialize(student))


def _terminate_plan_effects(plan):
    """Cancel SCHEDULED trips and release committed budget for a plan."""
    was_committed = plan["status"] in ("ACTIVE", "SUSPENDED")
    for trip in DB["trips"].values():
        if trip["transportation_plan_id"] == plan["id"] and trip["status"] == "SCHEDULED":
            trip["status"] = "CANCELED"
            touch(trip)
    if was_committed:
        committed = plan.get("_committed_cents", 0)
        if committed:
            district = DB["districts"].get(plan["serving_district_id"])
            if district is not None:
                district["committed_cost_cents"] -= committed
                touch(district)
        plan["_committed_cents"] = 0
    plan["status"] = "TERMINATED"
    touch(plan)


@app.route("/mv/students/<student_id>/withdraw", methods=["POST"])
def withdraw_student(student_id):
    require_auth(["Registrar", "StateCoordinator"])
    student = resolve("students", student_id)
    if student["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Student not in ENROLLED state")
    student["status"] = "WITHDRAWN"
    touch(student)
    # Cascade 1: terminate plans in APPROVED/ACTIVE/SUSPENDED
    for plan in list(DB["plans"].values()):
        if plan["student_id"] == student_id and plan["status"] in ("APPROVED", "ACTIVE", "SUSPENDED"):
            _terminate_plan_effects(plan)
    # Cascade 2: revoke ACTIVE benefit links
    for bl in list(DB["benefit_links"].values()):
        if bl["student_id"] == student_id and bl["status"] == "ACTIVE":
            bl["status"] = "REVOKED"
            touch(bl)
            district = DB["districts"].get(bl["district_id"])
            if district is not None:
                district["categorical_eligible_count"] -= 1
                touch(district)
    # Eligibility unchanged, but caseload must drop since student is WITHDRAWN
    recompute_caseload(DB["liaisons"].get(student.get("liaison_id")))
    return ok(serialize(student))


@app.route("/mv/students/<student_id>/assign-liaison", methods=["POST"])
def assign_liaison(student_id):
    require_auth(["Liaison", "StateCoordinator"])
    student = resolve("students", student_id)
    body = get_body()
    require_fields(body, ["liaison_id"])
    liaison_id = require_str(body, "liaison_id")
    liaison = resolve("liaisons", liaison_id)
    # caseload boundary: prospective eligible non-withdrawn count including this student
    prospective = 0
    for s in DB["students"].values():
        if s["id"] == student_id:
            continue
        if (s.get("liaison_id") == liaison_id and s["status"] != "WITHDRAWN"
                and s["eligibility_status"] == "ELIGIBLE"):
            prospective += 1
    if student["status"] != "WITHDRAWN" and student["eligibility_status"] == "ELIGIBLE":
        prospective += 1
    if prospective > liaison["max_caseload"]:
        raise ApiError("ERR_LIAISON_CASELOAD_FULL", 409, "Liaison caseload would be exceeded")
    prev_liaison_id = student.get("liaison_id")
    student["liaison_id"] = liaison_id
    touch(student)
    recompute_caseload(liaison)
    if prev_liaison_id and prev_liaison_id != liaison_id:
        recompute_caseload(DB["liaisons"].get(prev_liaison_id))
    return ok(serialize(student))


@app.route("/mv/students/<student_id>/eligibility-determinations", methods=["POST"])
def create_determination(student_id):
    require_auth(["Liaison", "StateCoordinator"])
    student = resolve("students", student_id)
    body = get_body()
    require_fields(body, ["category", "basis", "decision", "effective_date",
                          "expected_student_version"])
    category = require_enum(body, "category", DET_CATEGORIES)
    basis = require_enum(body, "basis", DET_BASES)
    decision = require_enum(body, "decision", DET_DECISIONS)
    effective_date = require_str(body, "effective_date")
    expected = body["expected_student_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 422, "expected_student_version must be an integer")
    # OCC
    if expected != student["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Student version is stale")
    rec = new_record(common=True)
    rec.update({
        "student_id": student_id,
        "category": category,
        "basis": basis,
        "decision": decision,
        "effective_date": effective_date,
        "status": "DRAFT",
    })
    DB["determinations"][rec["id"]] = rec
    touch(student)  # increments student.version by 1
    return ok(serialize(rec), status=201)


@app.route("/mv/eligibility-determinations/<determination_id>", methods=["GET"])
def get_determination(determination_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("determinations", determination_id)))


@app.route("/mv/eligibility-determinations", methods=["GET"])
def list_determinations():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["determinations"].values())
    sid = request.args.get("student_id")
    if sid:
        recs = [r for r in recs if r["student_id"] == sid]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/eligibility-determinations/<determination_id>/finalize", methods=["POST"])
def finalize_determination(determination_id):
    require_auth(["Liaison", "StateCoordinator"])
    det = resolve("determinations", determination_id)
    if det["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Determination not in DRAFT state")
    student = DB["students"].get(det["student_id"])
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND", 404, "Student not found")
    if student["status"] == "WITHDRAWN":
        raise ApiError("ERR_STUDENT_WITHDRAWN", 409, "Student is withdrawn")
    det["status"] = "FINALIZED"
    touch(det)
    # Hop 1: student eligibility + final priority
    student["eligibility_status"] = det["decision"]
    student["priority_score"] = compute_priority_final(det)
    student["priority_basis"] = "FINAL"
    touch(student)
    # Hop 2 & 3: benefit link + district counter
    if det["decision"] == "ELIGIBLE" and not student_active_benefit_links(student["id"]):
        create_benefit_link(student)
    # caseload recompute (eligibility may have changed)
    recompute_caseload(DB["liaisons"].get(student.get("liaison_id")))
    return ok(serialize(det))


# ---------------------------------------------------------------------------
# TransportationPlan
# ---------------------------------------------------------------------------
@app.route("/mv/transportation-plans", methods=["POST"])
def create_plan():
    require_auth(["TransportCoordinator", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["student_id", "origin_district_id",
                          "serving_district_id", "route_miles"])
    student_id = require_str(body, "student_id")
    origin_id = require_str(body, "origin_district_id")
    serving_id = require_str(body, "serving_district_id")
    route_miles = require_nonneg_int(body, "route_miles")
    resolve("students", student_id)
    resolve("districts", origin_id)
    resolve("districts", serving_id)
    daily = route_miles * PER_MILE_RATE_CENTS + BASE_TRIP_CENTS
    monthly = daily * SCHOOL_DAYS_PER_MONTH
    rec = new_record(common=True)
    rec.update({
        "student_id": student_id,
        "origin_district_id": origin_id,
        "serving_district_id": serving_id,
        "route_miles": route_miles,
        "estimated_daily_cost_cents": daily,
        "estimated_monthly_cost_cents": monthly,
        "actual_cost_cents": 0,
        "status": "DRAFT",
        "_committed_cents": 0,
    })
    DB["plans"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/transportation-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("plans", plan_id)))


@app.route("/mv/transportation-plans", methods=["GET"])
def list_plans():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["plans"].values())
    for key in ("student_id", "origin_district_id", "serving_district_id"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


def _plan_transition(plan_id, allowed_from, target):
    plan = resolve("plans", plan_id)
    if plan["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, f"Plan not in {allowed_from}")
    return plan


@app.route("/mv/transportation-plans/<plan_id>/submit", methods=["POST"])
def submit_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = _plan_transition(plan_id, ["DRAFT"], "PROPOSED")
    plan["status"] = "PROPOSED"
    touch(plan)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = resolve("plans", plan_id)
    if plan["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan not in PROPOSED state")
    student = DB["students"].get(plan["student_id"])
    if student is None or student["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_STUDENT_NOT_ELIGIBLE", 409, "Student is not ELIGIBLE")
    plan["status"] = "APPROVED"
    touch(plan)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/deny", methods=["POST"])
def deny_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = _plan_transition(plan_id, ["PROPOSED"], "DENIED")
    plan["status"] = "DENIED"
    touch(plan)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = resolve("plans", plan_id)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan not in APPROVED state")
    agreement = latest_agreement_for_plan(plan_id)
    if agreement is None:
        raise ApiError("ERR_NO_COST_SHARE", 409, "No cost-share agreement for plan")
    district = DB["districts"].get(plan["serving_district_id"])
    share = agreement["serving_share_cents"]
    committed = district["committed_cost_cents"] if district else 0
    budget = district["transport_budget_cents"] if district else 0
    if committed + share > budget:
        raise ApiError("ERR_BUDGET_EXCEEDED", 409, "Serving district budget exceeded")
    plan["status"] = "ACTIVE"
    plan["_committed_cents"] = share
    touch(plan)
    if district is not None:
        district["committed_cost_cents"] += share
        touch(district)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/suspend", methods=["POST"])
def suspend_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = _plan_transition(plan_id, ["ACTIVE"], "SUSPENDED")
    plan["status"] = "SUSPENDED"
    touch(plan)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/resume", methods=["POST"])
def resume_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = _plan_transition(plan_id, ["SUSPENDED"], "ACTIVE")
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/terminate", methods=["POST"])
def terminate_plan(plan_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    plan = resolve("plans", plan_id)
    if plan["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Plan not ACTIVE or SUSPENDED")
    _terminate_plan_effects(plan)
    return ok(serialize(plan))


@app.route("/mv/transportation-plans/<plan_id>/cost-summary", methods=["GET"])
def plan_cost_summary(plan_id):
    require_auth(ALL_ROLES)
    plan = resolve("plans", plan_id)
    completed = [t for t in DB["trips"].values()
                 if t["transportation_plan_id"] == plan_id and t["status"] == "COMPLETED"]
    actual = sum(t["trip_cost_cents"] for t in completed)
    return ok({
        "estimated_daily_cost_cents": plan["estimated_daily_cost_cents"],
        "estimated_monthly_cost_cents": plan["estimated_monthly_cost_cents"],
        "actual_cost_cents": actual,
        "completed_trip_count": len(completed),
    })


# ---------------------------------------------------------------------------
# CostShareAgreement
# ---------------------------------------------------------------------------
def tier_pct(route_miles):
    if route_miles <= 10:
        return 0.50
    if route_miles <= 25:
        return 0.60
    return 0.75


@app.route("/mv/cost-share-agreements", methods=["POST"])
def create_agreement():
    require_auth(["TransportCoordinator", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["transportation_plan_id", "expected_transportation_plan_version"])
    plan_id = require_str(body, "transportation_plan_id")
    expected = body["expected_transportation_plan_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 422, "expected_transportation_plan_version must be an integer")
    plan = resolve("plans", plan_id)
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Plan version is stale")
    total_monthly = plan["estimated_monthly_cost_cents"]
    pct = tier_pct(plan["route_miles"])
    serving_share = min(SHARE_CAP_CENTS, serving_delta(total_monthly, pct))
    origin_share = total_monthly - serving_share
    rec = new_record(common=True)
    rec.update({
        "transportation_plan_id": plan_id,
        "origin_district_id": plan["origin_district_id"],
        "serving_district_id": plan["serving_district_id"],
        "total_monthly_cents": total_monthly,
        "serving_pct": pct,
        "serving_share_cents": serving_share,
        "origin_share_cents": origin_share,
        "actual_cost_cents": 0,
    })
    DB["agreements"][rec["id"]] = rec
    touch(plan)  # increments plan.version by 1
    return ok(serialize(rec), status=201)


@app.route("/mv/cost-share-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("agreements", agreement_id)))


@app.route("/mv/cost-share-agreements", methods=["GET"])
def list_agreements():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["agreements"].values())
    pid = request.args.get("transportation_plan_id")
    if pid:
        recs = [r for r in recs if r["transportation_plan_id"] == pid]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/cost-share-agreements/<agreement_id>/invoice", methods=["GET"])
def agreement_invoice(agreement_id):
    require_auth(ALL_ROLES)
    agreement = resolve("agreements", agreement_id)
    pct = agreement["serving_pct"]
    plan_id = agreement["transportation_plan_id"]
    completed = [t for t in DB["trips"].values()
                 if t["transportation_plan_id"] == plan_id and t["status"] == "COMPLETED"]
    serving_total = 0
    origin_total = 0
    for t in completed:
        serving_portion = serving_delta(t["trip_cost_cents"], pct)
        serving_total += serving_portion
        origin_total += t["trip_cost_cents"] - serving_portion
    return ok({
        "serving_invoice_cents": serving_total,
        "origin_invoice_cents": origin_total,
        "trip_count": len(completed),
    })


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
@app.route("/mv/vehicles", methods=["POST"])
def create_vehicle():
    require_auth(["TransportCoordinator", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["serving_district_id", "label", "capacity_students"])
    serving_id = require_str(body, "serving_district_id")
    label = require_str(body, "label")
    capacity = require_nonneg_int(body, "capacity_students")
    resolve("districts", serving_id)
    rec = new_record(common=True)
    rec.update({
        "serving_district_id": serving_id,
        "label": label,
        "capacity_students": capacity,
        "status": "IN_SERVICE",
    })
    DB["vehicles"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("vehicles", vehicle_id)))


@app.route("/mv/vehicles", methods=["GET"])
def list_vehicles():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["vehicles"].values())
    sid = request.args.get("serving_district_id")
    if sid:
        recs = [r for r in recs if r["serving_district_id"] == sid]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


VEHICLE_TRANSITIONS = {
    ("IN_SERVICE", "OUT_OF_SERVICE"),
    ("OUT_OF_SERVICE", "IN_SERVICE"),
    ("IN_SERVICE", "RETIRED"),
    ("OUT_OF_SERVICE", "RETIRED"),
}


@app.route("/mv/vehicles/<vehicle_id>/set-status", methods=["POST"])
def set_vehicle_status(vehicle_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    vehicle = resolve("vehicles", vehicle_id)
    body = get_body()
    require_fields(body, ["status"])
    target = require_enum(body, "status", VEHICLE_STATUSES)
    if (vehicle["status"], target) not in VEHICLE_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal vehicle status transition")
    vehicle["status"] = target
    touch(vehicle)
    return ok(serialize(vehicle))


# ---------------------------------------------------------------------------
# TripAssignment
# ---------------------------------------------------------------------------
def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@app.route("/mv/trip-assignments", methods=["POST"])
def create_trip():
    require_auth(["TransportCoordinator", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["transportation_plan_id", "vehicle_id",
                          "scheduled_start", "scheduled_end"])
    plan_id = require_str(body, "transportation_plan_id")
    vehicle_id = require_str(body, "vehicle_id")
    # existence left to right
    plan = resolve("plans", plan_id)
    vehicle = resolve("vehicles", vehicle_id)
    # body well-formedness (422) before state (409)
    start = parse_dt(body["scheduled_start"], "scheduled_start")
    end = parse_dt(body["scheduled_end"], "scheduled_end")
    if not (end > start):
        raise ApiError("ERR_VALIDATION", 422, "scheduled_end must be after scheduled_start")
    # state gates
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if vehicle["status"] != "IN_SERVICE":
        raise ApiError("ERR_VEHICLE_NOT_IN_SERVICE", 409, "Vehicle is not IN_SERVICE")
    # vehicle buffer conflict (same vehicle, SCHEDULED/COMPLETED, +/- buffer)
    buffer = timedelta(minutes=VEHICLE_BUFFER_MINUTES)
    for t in DB["trips"].values():
        if t["vehicle_id"] != vehicle_id:
            continue
        if t["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        ex_start = t["_start"] - buffer
        ex_end = t["_end"] + buffer
        if _windows_overlap(start, end, ex_start, ex_end):
            raise ApiError("ERR_VEHICLE_TIME_CONFLICT", 409, "Vehicle time conflict")
    # district concurrent cap (same serving district, SCHEDULED, plain overlap)
    serving_district_id = plan["serving_district_id"]
    overlapping = 0
    for t in DB["trips"].values():
        if t["status"] != "SCHEDULED":
            continue
        if t["serving_district_id"] != serving_district_id:
            continue
        if _windows_overlap(start, end, t["_start"], t["_end"]):
            overlapping += 1
    if overlapping >= DISTRICT_CONCURRENT_TRIP_CAP:
        raise ApiError("ERR_DISTRICT_CAPACITY", 409, "District concurrent trip cap exceeded")
    rec = new_record(common=True)
    rec.update({
        "transportation_plan_id": plan_id,
        "vehicle_id": vehicle_id,
        "serving_district_id": serving_district_id,
        "scheduled_start": fmt_ts(start),
        "scheduled_end": fmt_ts(end),
        "actual_miles": None,
        "trip_cost_cents": None,
        "status": "SCHEDULED",
        "_start": start,
        "_end": end,
    })
    DB["trips"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/trip-assignments/<trip_id>", methods=["GET"])
def get_trip(trip_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("trips", trip_id)))


@app.route("/mv/trip-assignments", methods=["GET"])
def list_trips():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["trips"].values())
    for key in ("transportation_plan_id", "vehicle_id"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/trip-assignments/<trip_id>/complete", methods=["POST"])
def complete_trip(trip_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    trip = resolve("trips", trip_id)
    body = get_body()
    require_fields(body, ["actual_miles"])
    actual_miles = require_nonneg_int(body, "actual_miles")
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip not in SCHEDULED state")
    trip_cost = actual_miles * PER_MILE_RATE_CENTS + BASE_TRIP_CENTS
    trip["actual_miles"] = actual_miles
    trip["trip_cost_cents"] = trip_cost
    trip["status"] = "COMPLETED"
    touch(trip)
    plan = DB["plans"].get(trip["transportation_plan_id"])
    agreement = latest_agreement_for_plan(trip["transportation_plan_id"])
    delta = 0
    if agreement is not None:
        delta = serving_delta(trip_cost, agreement["serving_pct"])
    # Hop 1: plan + agreement actuals
    if plan is not None:
        plan["actual_cost_cents"] += trip_cost
        touch(plan)
    if agreement is not None:
        agreement["actual_cost_cents"] += delta
        touch(agreement)
    # Hop 2: ledger entry (append-only)
    serving_district_id = trip["serving_district_id"]
    entry = new_record(common=False)
    entry.update({
        "cost_share_agreement_id": agreement["id"] if agreement else None,
        "district_id": serving_district_id,
        "trip_assignment_id": trip["id"],
        "entry_type": "TRIP_CHARGE",
        "amount_cents": delta,
        "memo": f"Trip charge for trip {trip['id']}",
    })
    DB["ledger_entries"][entry["id"]] = entry
    # Hop 3: district balance
    district = DB["districts"].get(serving_district_id)
    if district is not None:
        district["transport_balance_cents"] += delta
        touch(district)
    # record for reversal
    trip["_serving_delta"] = delta
    trip["_agreement_id"] = agreement["id"] if agreement else None
    return ok(serialize(trip))


@app.route("/mv/trip-assignments/<trip_id>/cancel", methods=["POST"])
def cancel_trip(trip_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    trip = resolve("trips", trip_id)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip not in SCHEDULED state")
    trip["status"] = "CANCELED"
    touch(trip)
    return ok(serialize(trip))


@app.route("/mv/trip-assignments/<trip_id>/void", methods=["POST"])
def void_trip(trip_id):
    require_auth(["TransportCoordinator", "StateCoordinator"])
    trip = resolve("trips", trip_id)
    if trip["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Trip not in COMPLETED state")
    trip["status"] = "VOIDED"
    touch(trip)
    trip_cost = trip["trip_cost_cents"]
    delta = trip.get("_serving_delta", 0)
    plan = DB["plans"].get(trip["transportation_plan_id"])
    agreement = DB["agreements"].get(trip.get("_agreement_id")) if trip.get("_agreement_id") else None
    if plan is not None:
        plan["actual_cost_cents"] -= trip_cost
        touch(plan)
    if agreement is not None:
        agreement["actual_cost_cents"] -= delta
        touch(agreement)
    serving_district_id = trip["serving_district_id"]
    entry = new_record(common=False)
    entry.update({
        "cost_share_agreement_id": trip.get("_agreement_id"),
        "district_id": serving_district_id,
        "trip_assignment_id": trip["id"],
        "entry_type": "REVERSAL",
        "amount_cents": -delta,
        "memo": f"Reversal for trip {trip['id']}",
    })
    DB["ledger_entries"][entry["id"]] = entry
    district = DB["districts"].get(serving_district_id)
    if district is not None:
        district["transport_balance_cents"] -= delta
        touch(district)
    return ok(serialize(trip))


# ---------------------------------------------------------------------------
# CostLedgerEntry (read-only)
# ---------------------------------------------------------------------------
@app.route("/mv/cost-ledger-entries/<ledger_entry_id>", methods=["GET"])
def get_ledger_entry(ledger_entry_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("ledger_entries", ledger_entry_id)))


@app.route("/mv/cost-ledger-entries", methods=["GET"])
def list_ledger_entries():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["ledger_entries"].values())
    for key in ("cost_share_agreement_id", "district_id"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# BenefitLink
# ---------------------------------------------------------------------------
@app.route("/mv/benefit-links/<benefit_link_id>", methods=["GET"])
def get_benefit_link(benefit_link_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("benefit_links", benefit_link_id)))


@app.route("/mv/benefit-links", methods=["GET"])
def list_benefit_links():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["benefit_links"].values())
    for key in ("student_id", "district_id"):
        val = request.args.get(key)
        if val:
            recs = [r for r in recs if r.get(key) == val]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/benefit-links/<benefit_link_id>/revoke", methods=["POST"])
def revoke_benefit_link(benefit_link_id):
    require_auth(["Liaison", "StateCoordinator"])
    bl = resolve("benefit_links", benefit_link_id)
    if bl["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Benefit link not ACTIVE")
    bl["status"] = "REVOKED"
    touch(bl)
    district = DB["districts"].get(bl["district_id"])
    if district is not None:
        district["categorical_eligible_count"] -= 1
        touch(district)
    return ok(serialize(bl))


# ---------------------------------------------------------------------------
# Dispute
# ---------------------------------------------------------------------------
@app.route("/mv/disputes", methods=["POST"])
def create_dispute():
    require_auth(["Liaison", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["student_id", "dispute_type", "description"])
    student_id = require_str(body, "student_id")
    dispute_type = require_enum(body, "dispute_type", DISPUTE_TYPES)
    description = require_str(body, "description")
    resolve("students", student_id)
    rec = new_record(common=True)
    rec.update({
        "student_id": student_id,
        "dispute_type": dispute_type,
        "description": description,
        "outcome": None,
        "status": "FILED",
    })
    DB["disputes"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("disputes", dispute_id)))


@app.route("/mv/disputes", methods=["GET"])
def list_disputes():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["disputes"].values())
    sid = request.args.get("student_id")
    if sid:
        recs = [r for r in recs if r["student_id"] == sid]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/disputes/<dispute_id>/begin-review", methods=["POST"])
def dispute_begin_review(dispute_id):
    require_auth(["StateCoordinator"])
    d = resolve("disputes", dispute_id)
    if d["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute not FILED")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return ok(serialize(d))


@app.route("/mv/disputes/<dispute_id>/request-info", methods=["POST"])
def dispute_request_info(dispute_id):
    require_auth(["StateCoordinator"])
    d = resolve("disputes", dispute_id)
    if d["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute not UNDER_REVIEW")
    d["status"] = "INFO_REQUESTED"
    touch(d)
    return ok(serialize(d))


@app.route("/mv/disputes/<dispute_id>/resubmit", methods=["POST"])
def dispute_resubmit(dispute_id):
    require_auth(["Liaison", "StateCoordinator"])
    d = resolve("disputes", dispute_id)
    if d["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute not INFO_REQUESTED")
    d["status"] = "FILED"
    touch(d)
    return ok(serialize(d))


@app.route("/mv/disputes/<dispute_id>/resolve", methods=["POST"])
def dispute_resolve(dispute_id):
    require_auth(["StateCoordinator"])
    d = resolve("disputes", dispute_id)
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = require_enum(body, "outcome", DISPUTE_OUTCOMES)
    if d["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute not UNDER_REVIEW")
    d["outcome"] = outcome
    d["status"] = "RESOLVED_UPHELD" if outcome == "UPHELD" else "RESOLVED_DENIED"
    touch(d)
    if outcome == "UPHELD":
        student = DB["students"].get(d["student_id"])
        if student is not None and student["eligibility_status"] != "ELIGIBLE":
            student["eligibility_status"] = "ELIGIBLE"
            touch(student)
            if not student_active_benefit_links(student["id"]):
                create_benefit_link(student)
            recompute_caseload(DB["liaisons"].get(student.get("liaison_id")))
    return ok(serialize(d))


# ---------------------------------------------------------------------------
# TutoringReferral
# ---------------------------------------------------------------------------
@app.route("/mv/tutoring-referrals", methods=["POST"])
def create_referral():
    require_auth(["Liaison", "StateCoordinator"])
    body = get_body()
    require_fields(body, ["student_id", "subject"])
    student_id = require_str(body, "student_id")
    subject = require_enum(body, "subject", REFERRAL_SUBJECTS)
    resolve("students", student_id)
    rec = new_record(common=True)
    rec.update({
        "student_id": student_id,
        "subject": subject,
        "status": "OPEN",
    })
    DB["referrals"][rec["id"]] = rec
    return ok(serialize(rec), status=201)


@app.route("/mv/tutoring-referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    require_auth(ALL_ROLES)
    return ok(serialize(resolve("referrals", referral_id)))


@app.route("/mv/tutoring-referrals", methods=["GET"])
def list_referrals():
    require_auth(ALL_ROLES)
    limit, offset = pagination()
    recs = list(DB["referrals"].values())
    sid = request.args.get("student_id")
    if sid:
        recs = [r for r in recs if r["student_id"] == sid]
    items, total = paginate_and_serialize(recs, limit, offset)
    return ok_list(items, limit, offset, total)


@app.route("/mv/tutoring-referrals/<referral_id>/close", methods=["POST"])
def close_referral(referral_id):
    require_auth(["Liaison", "StateCoordinator"])
    r = resolve("referrals", referral_id)
    if r["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Referral not OPEN")
    r["status"] = "CLOSED"
    touch(r)
    return ok(serialize(r))


@app.route("/mv/tutoring-referrals/<referral_id>/cancel", methods=["POST"])
def cancel_referral(referral_id):
    require_auth(["Liaison", "StateCoordinator"])
    r = resolve("referrals", referral_id)
    if r["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Referral not OPEN")
    r["status"] = "CANCELED"
    touch(r)
    return ok(serialize(r))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
