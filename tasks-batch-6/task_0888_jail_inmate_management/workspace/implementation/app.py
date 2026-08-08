"""Jail & Inmate Management API — Python + Flask, in-memory only.

Boots empty on every process start. No seeding. All state in module-level dicts.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_ROLES = {
    "IntakeOfficer", "ClassificationOfficer", "Scheduler",
    "HealthGrievanceOfficer", "Supervisor", "Visitor",
}
STAFF5 = ["IntakeOfficer", "ClassificationOfficer", "Scheduler",
          "HealthGrievanceOfficer", "Supervisor"]

STATUTORY_RATE = Decimal("0.10")
EARNED_CAP_RATE = Decimal("0.20")
ACCRUAL_BY_LEVEL = {"MIN": Decimal("0.25"), "MED": Decimal("0.15"), "MAX": Decimal("0.05")}

SEVERITY_POINTS = {"FELONY": 30, "MISDEMEANOR": 10, "INFRACTION": 5}
HISTORY_PER_PRIOR = 6
HISTORY_CAP = 30
BEHAVIOR_PER_UPHELD = 15
MED_THRESHOLD = 25
MAX_THRESHOLD = 55

TAX_RATE = Decimal("0.0725")
SERVICE_FEE_CENTS = 25
VISIT_BUFFER = timedelta(minutes=30)

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Enum domains
SEX = {"MALE", "FEMALE"}
CHARGE_SEVERITY = {"FELONY", "MISDEMEANOR", "INFRACTION"}
ASSESSMENT_TYPE = {"INITIAL", "REASSESSMENT"}
SECURITY_LEVEL = {"MIN", "MED", "MAX"}
UNIT_GENDER = {"MALE", "FEMALE", "COED"}
EVENT_TYPE = {"ARRAIGNMENT", "HEARING", "TRIAL", "SENTENCING"}
RELATIONSHIP = {"FAMILY", "ATTORNEY", "FRIEND", "CLERGY"}
REQUEST_TYPE = {"MEDICAL", "GRIEVANCE"}
INFRACTION_TYPE = {"CONTRABAND", "ASSAULT", "DISOBEDIENCE", "PROPERTY_DAMAGE"}
PROPERTY_CATEGORY = {"CLOTHING", "ELECTRONICS", "CASH", "DOCUMENTS", "OTHER"}
RELEASE_REASON = {"TIME_SERVED", "COURT_ORDER", "BOND", "BAIL"}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "inmates": {}, "bookings": {}, "assessments": {}, "housing_units": {},
    "beds": {}, "assignments": {}, "court_events": {}, "commissary_accounts": {},
    "orders": {}, "visitors": {}, "visits": {}, "requests": {},
    "infractions": {}, "property_items": {},
}
_clock = {"current_utc": CLOCK_DEFAULT}
_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def err_response(error_id, http_status, message):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _nf(e):
    return err_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def _mna(e):
    return err_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def _unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e.error_id, e.http_status, e.message)
    return err_response("ERR_INTERNAL", 500, str(e))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body helpers
# ---------------------------------------------------------------------------
def body_json():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return b


def require_present(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 422, f"missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = require_present(body, name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"field {name} must be a non-empty string")
    return v


def req_int(body, name, minimum=None, exclusive_min=None):
    v = require_present(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 422, f"field {name} must be >= {minimum}")
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError("ERR_VALIDATION", 422, f"field {name} must be > {exclusive_min}")
    return v


def req_enum(body, name, domain):
    v = require_present(body, name)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"field {name} must be a string")
    if v not in domain:
        raise ApiError("ERR_INVALID_ENUM", 422, f"field {name} is not a valid member")
    return v


def parse_dt(s, field="datetime"):
    if not isinstance(s, str) or not s:
        raise ApiError("ERR_VALIDATION", 422, f"field {field} must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"field {field} is not a valid ISO 8601 datetime")


def get_or_404(coll, _id, kind):
    o = db[coll].get(_id)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{kind} not found")
    return o


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def base_fields():
    t = now_iso()
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t,
            "version": 1, "_seq": next_seq()}


def bump(obj):
    obj["version"] += 1
    obj["updated_at"] = now_iso()


def touch_time(obj):
    obj["updated_at"] = now_iso()


def public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def serialize_inmate(obj):
    d = public(obj)
    d["status"] = derive_inmate_status(obj["id"])
    return d


def derive_inmate_status(inmate_id):
    bks = [b for b in db["bookings"].values() if b["inmate_id"] == inmate_id]
    if not bks:
        return "IN_CUSTODY"
    latest = max(bks, key=lambda b: b["_seq"])
    return "RELEASED" if latest["booking_status"] == "RELEASED" else "IN_CUSTODY"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items: already-sorted list of raw entity dicts. Returns (page, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
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
    has_more = (offset + len(page)) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def list_response(raw_items, serializer=public):
    ordered = sorted(raw_items, key=lambda o: o["_seq"])
    page, pg = paginate(ordered)
    return ok([serializer(o) for o in page], status=200, response_type="array", pagination=pg)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def floor_mul(days, rate):
    return int((Decimal(days) * rate).to_integral_value(rounding=ROUND_FLOOR))


def add_days(date_str, n):
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return (d + timedelta(days=n)).strftime("%Y-%m-%d")


def recompute_good_time(b):
    sd = b["sentence_days"]
    b["statutory_good_time_days"] = floor_mul(sd, STATUTORY_RATE)
    b["statutory_release_date"] = add_days(b["sentence_start_date"], sd - b["statutory_good_time_days"])
    level = b["classification_level"]
    rate = ACCRUAL_BY_LEVEL.get(level) if level else None
    if rate is None:
        accrued = 0
    else:
        accrued = floor_mul(sd, rate)
    cap = floor_mul(sd, EARNED_CAP_RATE)
    earned = max(0, min(cap, accrued - b["total_forfeited_days"]))
    b["earned_good_time_days"] = earned
    b["projected_release_date"] = add_days(b["sentence_start_date"], sd - earned)


def classify_score(b, atype):
    sev = SEVERITY_POINTS[b["charge_severity"]]
    hist = min(HISTORY_CAP, b["prior_bookings_count"] * HISTORY_PER_PRIOR)
    if atype == "REASSESSMENT":
        upheld = sum(1 for i in db["infractions"].values()
                     if i["booking_id"] == b["id"] and i["infraction_status"] == "UPHELD")
        beh = BEHAVIOR_PER_UPHELD * upheld
    else:
        beh = 0
    total = sev + hist + beh
    level = "MAX" if total >= MAX_THRESHOLD else ("MED" if total >= MED_THRESHOLD else "MIN")
    return sev, hist, beh, total, level


def rhu_cents(dec):
    return int(dec.to_integral_value(rounding=ROUND_HALF_UP))


def get_current_date():
    return parse_dt(_clock["current_utc"]).date()


# ===========================================================================
# ROUTES
# ===========================================================================
@app.route("/", methods=["GET"])
def root():
    return ok({"service": "jail-inmate-management"})


# --- Clock (test driver) ---
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth(["Supervisor"])
    body = body_json()
    to_iso = req_str(body, "to_iso8601")
    parse_dt(to_iso, "to_iso8601")  # validate parseable
    _clock["current_utc"] = to_iso
    return ok({"current_utc": to_iso})


# --- Inmate ---
@app.route("/inmates", methods=["POST"])
def create_inmate():
    auth(["IntakeOfficer"])
    body = body_json()
    full_name = req_str(body, "full_name")
    dob = req_str(body, "date_of_birth")
    sex = req_enum(body, "sex", SEX)
    obj = base_fields()
    obj.update({"full_name": full_name, "date_of_birth": dob, "sex": sex,
                "status": "IN_CUSTODY"})
    db["inmates"][obj["id"]] = obj
    return ok(serialize_inmate(obj), status=201)


@app.route("/inmates/<iid>", methods=["GET"])
def get_inmate(iid):
    auth(STAFF5)
    obj = get_or_404("inmates", iid, "inmate")
    return ok(serialize_inmate(obj))


@app.route("/inmates/<iid>/bookings", methods=["GET"])
def list_inmate_bookings(iid):
    auth(STAFF5)
    get_or_404("inmates", iid, "inmate")
    items = [b for b in db["bookings"].values() if b["inmate_id"] == iid]
    return list_response(items)


@app.route("/inmates/<iid>/visitors", methods=["GET"])
def list_inmate_visitors(iid):
    auth(STAFF5)
    get_or_404("inmates", iid, "inmate")
    items = [v for v in db["visitors"].values() if v["inmate_id"] == iid]
    return list_response(items)


@app.route("/inmates/<iid>/visitors", methods=["POST"])
def register_visitor(iid):
    auth(["Scheduler"])
    get_or_404("inmates", iid, "inmate")
    body = body_json()
    name = req_str(body, "visitor_name")
    rel = req_enum(body, "relationship", RELATIONSHIP)
    obj = base_fields()
    obj.update({"inmate_id": iid, "visitor_name": name, "relationship": rel,
                "visitor_status": "PENDING"})
    db["visitors"][obj["id"]] = obj
    return ok(public(obj), status=201)


# --- Booking ---
@app.route("/bookings", methods=["POST"])
def create_booking():
    auth(["IntakeOfficer"])
    body = body_json()
    inmate_id = req_str(body, "inmate_id")
    arrest_dt = req_str(body, "arrest_datetime")
    severity = req_enum(body, "charge_severity", CHARGE_SEVERITY)
    prior = req_int(body, "prior_bookings_count", minimum=0)
    sentence_days = req_int(body, "sentence_days", exclusive_min=0)
    start_date = req_str(body, "sentence_start_date")
    # body-FK existence
    get_or_404("inmates", inmate_id, "inmate")

    obj = base_fields()
    obj.update({
        "inmate_id": inmate_id, "booking_status": "BOOKED",
        "arrest_datetime": arrest_dt, "charge_severity": severity,
        "prior_bookings_count": prior, "sentence_days": sentence_days,
        "sentence_start_date": start_date, "classification_level": None,
        "total_forfeited_days": 0, "statutory_good_time_days": 0,
        "earned_good_time_days": 0, "statutory_release_date": None,
        "projected_release_date": None, "release_reason": None,
    })
    recompute_good_time(obj)
    db["bookings"][obj["id"]] = obj

    acct = base_fields()
    acct.update({"booking_id": obj["id"], "balance_cents": 0, "total_deposited_cents": 0})
    db["commissary_accounts"][acct["id"]] = acct
    return ok(public(obj), status=201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    auth(STAFF5)
    obj = get_or_404("bookings", bid, "booking")
    return ok(public(obj))


@app.route("/bookings/<bid>/release-projection", methods=["GET"])
def release_projection(bid):
    auth(STAFF5)
    b = get_or_404("bookings", bid, "booking")
    data = {
        "classification_level": b["classification_level"],
        "total_forfeited_days": b["total_forfeited_days"],
        "statutory_good_time_days": b["statutory_good_time_days"],
        "earned_good_time_days": b["earned_good_time_days"],
        "statutory_release_date": b["statutory_release_date"],
        "projected_release_date": b["projected_release_date"],
    }
    return ok(data)


@app.route("/bookings/<bid>/classifications", methods=["POST"])
def create_classification(bid):
    auth(["ClassificationOfficer"])
    b = get_or_404("bookings", bid, "booking")
    body = body_json()
    atype = req_enum(body, "assessment_type", ASSESSMENT_TYPE)
    expected = req_int(body, "expected_booking_version")
    # OCC (priority 20)
    if expected != b["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_booking_version does not match current version")
    # source-state (priority 33)
    if atype == "INITIAL":
        if b["booking_status"] != "BOOKED":
            raise ApiError("ERR_INVALID_STATE", 409, "INITIAL assessment requires a BOOKED booking")
    else:  # REASSESSMENT
        if b["booking_status"] not in ("CLASSIFIED", "HOUSED"):
            raise ApiError("ERR_INVALID_STATE", 409, "REASSESSMENT requires a CLASSIFIED or HOUSED booking")

    sev, hist, beh, total, level = classify_score(b, atype)
    a = {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": next_seq(),
         "booking_id": bid, "assessment_type": atype, "severity_points": sev,
         "history_points": hist, "behavior_points": beh, "total_score": total,
         "resulting_level": level}
    db["assessments"][a["id"]] = a

    b["classification_level"] = level
    if atype == "INITIAL":
        b["booking_status"] = "CLASSIFIED"
    recompute_good_time(b)
    bump(b)
    return ok(public(a), status=201)


@app.route("/bookings/<bid>/classifications", methods=["GET"])
def list_classifications(bid):
    auth(["ClassificationOfficer", "Supervisor"])
    get_or_404("bookings", bid, "booking")
    items = [a for a in db["assessments"].values() if a["booking_id"] == bid]
    return list_response(items)


@app.route("/bookings/<bid>/release", methods=["POST"])
def release_booking(bid):
    auth(["Supervisor"])
    b = get_or_404("bookings", bid, "booking")
    body = body_json()
    reason = req_enum(body, "release_reason", RELEASE_REASON)
    # source-state: must be releasable (not already RELEASED)
    if b["booking_status"] == "RELEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "booking already RELEASED")
    # eligibility
    if reason == "TIME_SERVED":
        if b["projected_release_date"] is None or get_current_date() < datetime.strptime(
                b["projected_release_date"], "%Y-%m-%d").date():
            raise ApiError("ERR_NOT_RELEASE_ELIGIBLE", 409,
                           "current date has not reached projected_release_date")
    # discretionary reasons always eligible

    # cascade: end active housing assignment
    if b["booking_status"] == "HOUSED":
        for a in db["assignments"].values():
            if a["booking_id"] == bid and a["assignment_status"] == "ACTIVE":
                a["assignment_status"] = "ENDED"
                bump(a)
                bed = db["beds"].get(a["bed_id"])
                if bed is not None:
                    bed["status"] = "AVAILABLE"
                    bump(bed)
    # return stored property
    for p in db["property_items"].values():
        if p["booking_id"] == bid and p["property_status"] == "STORED":
            p["property_status"] = "RETURNED"
            bump(p)

    b["booking_status"] = "RELEASED"
    b["release_reason"] = reason
    touch_time(b)

    inmate = db["inmates"].get(b["inmate_id"])
    if inmate is not None:
        inmate["status"] = "RELEASED"
        bump(inmate)
    return ok(public(b))


# --- Housing ---
@app.route("/housing-units", methods=["POST"])
def create_unit():
    auth(["ClassificationOfficer"])
    body = body_json()
    name = req_str(body, "name")
    sec = req_enum(body, "security_level", SECURITY_LEVEL)
    gender = req_enum(body, "gender", UNIT_GENDER)
    cap = req_int(body, "capacity", exclusive_min=0)
    obj = base_fields()
    obj.update({"name": name, "security_level": sec, "gender": gender, "capacity": cap})
    db["housing_units"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/housing-units/<uid>", methods=["GET"])
def get_unit(uid):
    auth(["ClassificationOfficer", "Supervisor"])
    obj = get_or_404("housing_units", uid, "housing unit")
    return ok(public(obj))


@app.route("/housing-units/<uid>/beds", methods=["POST"])
def create_bed(uid):
    auth(["ClassificationOfficer"])
    get_or_404("housing_units", uid, "housing unit")
    body = body_json()
    label = req_str(body, "bed_label")
    obj = base_fields()
    obj.update({"housing_unit_id": uid, "bed_label": label, "status": "AVAILABLE"})
    db["beds"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/housing-units/<uid>/beds", methods=["GET"])
def list_beds(uid):
    auth(["ClassificationOfficer", "Supervisor"])
    get_or_404("housing_units", uid, "housing unit")
    items = [x for x in db["beds"].values() if x["housing_unit_id"] == uid]
    return list_response(items)


def _active_assignments_on_bed(bed_id):
    return [a for a in db["assignments"].values()
            if a["bed_id"] == bed_id and a["assignment_status"] == "ACTIVE"]


@app.route("/housing-assignments", methods=["POST"])
def create_assignment():
    auth(["ClassificationOfficer"])
    body = body_json()
    booking_id = req_str(body, "booking_id")
    bed_id = req_str(body, "bed_id")
    start_raw = req_str(body, "start_datetime")
    end_raw = body.get("end_datetime")
    # body-FK existence (left to right)
    b = get_or_404("bookings", booking_id, "booking")
    bed = get_or_404("beds", bed_id, "bed")
    # time range (priority 12)
    start_dt = parse_dt(start_raw, "start_datetime")
    end_dt = None
    if end_raw is not None:
        end_dt = parse_dt(end_raw, "end_datetime")
        if not (end_dt > start_dt):
            raise ApiError("ERR_INVALID_TIME_RANGE", 422, "end_datetime must be strictly after start_datetime")
    # booking not released (30)
    if b["booking_status"] == "RELEASED":
        raise ApiError("ERR_BOOKING_RELEASED", 409, "booking is RELEASED")
    # booking classified (31)
    if b["booking_status"] != "CLASSIFIED":
        raise ApiError("ERR_BOOKING_NOT_CLASSIFIED", 409, "booking must be CLASSIFIED before housing")
    unit = db["housing_units"].get(bed["housing_unit_id"])
    inmate = db["inmates"].get(b["inmate_id"])
    # security level (50)
    if unit["security_level"] != b["classification_level"]:
        raise ApiError("ERR_SECURITY_LEVEL_MISMATCH", 409, "bed unit security level does not match classification")
    # gender (51)
    if unit["gender"] != "COED" and unit["gender"] != inmate["sex"]:
        raise ApiError("ERR_GENDER_MISMATCH", 409, "unit gender does not accept inmate sex")
    # bed double-booked (60), half-open overlap
    for a in _active_assignments_on_bed(bed_id):
        a_s = parse_dt(a["start_datetime"])
        a_e = parse_dt(a["end_datetime"]) if a["end_datetime"] else None
        cond1 = (a_e is None) or (start_dt < a_e)
        cond2 = (end_dt is None) or (a_s < end_dt)
        if cond1 and cond2:
            raise ApiError("ERR_BED_DOUBLE_BOOKED", 409, "bed interval overlaps an active assignment")
    # housing unit full (62)
    occupied = sum(1 for x in db["beds"].values()
                   if x["housing_unit_id"] == unit["id"] and x["status"] == "OCCUPIED")
    if occupied >= unit["capacity"]:
        raise ApiError("ERR_HOUSING_UNIT_FULL", 409, "housing unit at capacity")

    obj = base_fields()
    obj.update({"booking_id": booking_id, "bed_id": bed_id,
                "start_datetime": start_raw, "end_datetime": end_raw,
                "assignment_status": "ACTIVE"})
    db["assignments"][obj["id"]] = obj
    bed["status"] = "OCCUPIED"
    bump(bed)
    b["booking_status"] = "HOUSED"
    touch_time(b)
    return ok(public(obj), status=201)


@app.route("/housing-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    auth(["ClassificationOfficer", "Supervisor"])
    obj = get_or_404("assignments", aid, "housing assignment")
    return ok(public(obj))


@app.route("/housing-assignments", methods=["GET"])
def list_assignments():
    auth(["ClassificationOfficer", "Supervisor"])
    booking_id = request.args.get("booking_id")
    bed_id = request.args.get("bed_id")
    items = list(db["assignments"].values())
    if booking_id is not None:
        items = [a for a in items if a["booking_id"] == booking_id]
    if bed_id is not None:
        items = [a for a in items if a["bed_id"] == bed_id]
    return list_response(items)


@app.route("/housing-assignments/<aid>/end", methods=["POST"])
def end_assignment(aid):
    auth(["ClassificationOfficer"])
    a = get_or_404("assignments", aid, "housing assignment")
    if a["assignment_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment is not ACTIVE")
    a["assignment_status"] = "ENDED"
    bump(a)
    bed = db["beds"].get(a["bed_id"])
    if bed is not None:
        bed["status"] = "AVAILABLE"
        bump(bed)
    b = db["bookings"].get(a["booking_id"])
    if b is not None and b["booking_status"] == "HOUSED":
        b["booking_status"] = "CLASSIFIED"
        touch_time(b)
    return ok(public(a))


# --- Commissary ---
@app.route("/bookings/<bid>/commissary-account", methods=["GET"])
def get_booking_account(bid):
    auth(["IntakeOfficer", "Supervisor"])
    get_or_404("bookings", bid, "booking")
    items = [ac for ac in db["commissary_accounts"].values() if ac["booking_id"] == bid]
    return list_response(items)


@app.route("/commissary-accounts/<acid>", methods=["GET"])
def get_account(acid):
    auth(["IntakeOfficer", "Supervisor"])
    obj = get_or_404("commissary_accounts", acid, "commissary account")
    return ok(public(obj))


@app.route("/commissary-accounts/<acid>/deposits", methods=["POST"])
def deposit(acid):
    auth(["IntakeOfficer"])
    ac = get_or_404("commissary_accounts", acid, "commissary account")
    body = body_json()
    amount = req_int(body, "amount_cents", exclusive_min=0)
    ac["balance_cents"] += amount
    ac["total_deposited_cents"] += amount
    bump(ac)
    return ok(public(ac))


def compute_order_total(lines):
    total = 0
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError("ERR_VALIDATION", 422, "each order line must be an object")
        if "item_name" not in line or not isinstance(line.get("item_name"), str) or line["item_name"] == "":
            raise ApiError("ERR_VALIDATION", 422, "line item_name is required")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError("ERR_VALIDATION", 422, "line quantity must be a positive integer")
        up = line.get("unit_price_cents")
        if isinstance(up, bool) or not isinstance(up, int) or up < 0:
            raise ApiError("ERR_VALIDATION", 422, "line unit_price_cents must be a non-negative integer")
        taxable = line.get("taxable")
        if not isinstance(taxable, bool):
            raise ApiError("ERR_VALIDATION", 422, "line taxable must be a boolean")
        raw = Decimal(qty) * Decimal(up)
        if taxable:
            raw = raw * (Decimal("1") + TAX_RATE)
        total += rhu_cents(raw)
    return total + SERVICE_FEE_CENTS


@app.route("/commissary-accounts/<acid>/orders", methods=["POST"])
def create_order(acid):
    auth(["IntakeOfficer"])
    ac = get_or_404("commissary_accounts", acid, "commissary account")
    body = body_json()
    lines = require_present(body, "lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError("ERR_VALIDATION", 422, "lines must be a non-empty array")
    expected = req_int(body, "expected_commissaryaccount_version")
    total = compute_order_total(lines)
    # OCC (20)
    if expected != ac["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_commissaryaccount_version does not match current version")
    # booking released (30)
    booking = db["bookings"].get(ac["booking_id"])
    if booking is not None and booking["booking_status"] == "RELEASED":
        raise ApiError("ERR_BOOKING_RELEASED", 409, "booking is RELEASED")
    # sufficient funds (70)
    if ac["balance_cents"] < total:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "insufficient funds for order total")

    obj = base_fields()
    obj.update({"commissary_account_id": acid, "lines": lines,
                "order_total_cents": total, "order_status": "PENDING"})
    db["orders"][obj["id"]] = obj
    bump(ac)
    return ok(public(obj), status=201)


@app.route("/commissary-accounts/<acid>/orders", methods=["GET"])
def list_orders(acid):
    auth(["IntakeOfficer", "Supervisor"])
    get_or_404("commissary_accounts", acid, "commissary account")
    items = [o for o in db["orders"].values() if o["commissary_account_id"] == acid]
    return list_response(items)


@app.route("/commissary-orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    auth(["IntakeOfficer"])
    o = get_or_404("orders", oid, "commissary order")
    if o["order_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "order is not PENDING")
    ac = db["commissary_accounts"].get(o["commissary_account_id"])
    if ac["balance_cents"] < o["order_total_cents"]:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 402, "insufficient funds to fulfill order")
    o["order_status"] = "FULFILLED"
    bump(o)
    ac["balance_cents"] -= o["order_total_cents"]
    bump(ac)
    return ok(public(o))


@app.route("/commissary-orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    auth(["Supervisor"])
    o = get_or_404("orders", oid, "commissary order")
    if o["order_status"] != "FULFILLED":
        raise ApiError("ERR_INVALID_STATE", 409, "order is not FULFILLED")
    ac = db["commissary_accounts"].get(o["commissary_account_id"])
    o["order_status"] = "REFUNDED"
    bump(o)
    ac["balance_cents"] += o["order_total_cents"]
    bump(ac)
    return ok(public(o))


# --- Court ---
@app.route("/bookings/<bid>/court-events", methods=["POST"])
def create_court_event(bid):
    auth(["Scheduler"])
    b = get_or_404("bookings", bid, "booking")
    body = body_json()
    event_dt = req_str(body, "event_datetime")
    event_type = req_enum(body, "event_type", EVENT_TYPE)
    transport = body.get("transport_required", True)
    if not isinstance(transport, bool):
        raise ApiError("ERR_VALIDATION", 422, "transport_required must be a boolean")
    if b["booking_status"] == "RELEASED":
        raise ApiError("ERR_BOOKING_RELEASED", 409, "booking is RELEASED")
    obj = base_fields()
    obj.update({"booking_id": bid, "event_datetime": event_dt, "event_type": event_type,
                "transport_required": transport, "court_event_status": "SCHEDULED",
                "continuance_count": 0})
    db["court_events"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/bookings/<bid>/court-events", methods=["GET"])
def list_court_events(bid):
    auth(["Scheduler", "Supervisor"])
    get_or_404("bookings", bid, "booking")
    items = [c for c in db["court_events"].values() if c["booking_id"] == bid]
    return list_response(items)


@app.route("/court-events/<cid>/continue", methods=["POST"])
def continue_court_event(cid):
    auth(["Scheduler"])
    c = get_or_404("court_events", cid, "court event")
    body = body_json()
    new_dt = req_str(body, "new_event_datetime")
    if c["court_event_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "court event is not SCHEDULED")
    c["continuance_count"] += 1
    c["event_datetime"] = new_dt
    # settles back in SCHEDULED
    bump(c)
    return ok(public(c))


@app.route("/court-events/<cid>/attend", methods=["POST"])
def attend_court_event(cid):
    auth(["Scheduler"])
    c = get_or_404("court_events", cid, "court event")
    if c["court_event_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "court event is not SCHEDULED")
    c["court_event_status"] = "ATTENDED"
    bump(c)
    return ok(public(c))


# --- Visitation ---
@app.route("/visitors/<vid>/approve", methods=["POST"])
def approve_visitor(vid):
    auth(["Scheduler"])
    v = get_or_404("visitors", vid, "visitor")
    if v["visitor_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "visitor is not PENDING")
    v["visitor_status"] = "APPROVED"
    bump(v)
    return ok(public(v))


@app.route("/visits", methods=["POST"])
def create_visit():
    uid, role = auth(["Scheduler", "Visitor"])
    body = body_json()
    booking_id = req_str(body, "booking_id")
    visitor_id = req_str(body, "visitor_id")
    start_raw = req_str(body, "start_datetime")
    end_raw = req_str(body, "end_datetime")
    # body-FK existence
    b = get_or_404("bookings", booking_id, "booking")
    v = get_or_404("visitors", visitor_id, "visitor")
    # visitor ownership for Visitor role
    if role == "Visitor" and visitor_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "a Visitor may act only on their own visits")
    # time range (12)
    start_dt = parse_dt(start_raw, "start_datetime")
    end_dt = parse_dt(end_raw, "end_datetime")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "end_datetime must be strictly after start_datetime")
    # booking released (30)
    if b["booking_status"] == "RELEASED":
        raise ApiError("ERR_BOOKING_RELEASED", 409, "booking is RELEASED")
    # visitor approved (35)
    if v["visitor_status"] != "APPROVED":
        raise ApiError("ERR_VISITOR_NOT_APPROVED", 409, "visitor is not APPROVED")
    # visit overlap (61): buffered closed interval on same booking, non-cancelled
    for ex in db["visits"].values():
        if ex["booking_id"] != booking_id or ex["visit_status"] == "CANCELLED":
            continue
        es = parse_dt(ex["start_datetime"]) - VISIT_BUFFER
        ee = parse_dt(ex["end_datetime"]) + VISIT_BUFFER
        if start_dt <= ee and es <= end_dt:
            raise ApiError("ERR_VISIT_OVERLAP", 409, "visit falls within buffer of another visit")

    obj = base_fields()
    obj.update({"booking_id": booking_id, "visitor_id": visitor_id,
                "start_datetime": start_raw, "end_datetime": end_raw,
                "visit_status": "REQUESTED"})
    db["visits"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    uid, role = auth(["Scheduler", "Supervisor", "Visitor"])
    v = get_or_404("visits", vid, "visit")
    if role == "Visitor" and v["visitor_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "a Visitor may read only their own visits")
    return ok(public(v))


@app.route("/visits", methods=["GET"])
def list_visits():
    auth(["Scheduler", "Supervisor"])
    booking_id = request.args.get("booking_id")
    visitor_id = request.args.get("visitor_id")
    items = list(db["visits"].values())
    if booking_id is not None:
        items = [x for x in items if x["booking_id"] == booking_id]
    if visitor_id is not None:
        items = [x for x in items if x["visitor_id"] == visitor_id]
    return list_response(items)


@app.route("/visits/<vid>/approve", methods=["POST"])
def approve_visit(vid):
    auth(["Scheduler"])
    v = get_or_404("visits", vid, "visit")
    if v["visit_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not REQUESTED")
    v["visit_status"] = "APPROVED"
    bump(v)
    return ok(public(v))


@app.route("/visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    uid, role = auth(["Scheduler", "Visitor"])
    v = get_or_404("visits", vid, "visit")
    if role == "Visitor" and v["visitor_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "a Visitor may cancel only their own visits")
    if v["visit_status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "visit is not REQUESTED or APPROVED")
    v["visit_status"] = "CANCELLED"
    bump(v)
    return ok(public(v))


# --- Medical / Grievance ---
@app.route("/bookings/<bid>/requests", methods=["POST"])
def create_request(bid):
    auth(["HealthGrievanceOfficer"])
    b = get_or_404("bookings", bid, "booking")
    body = body_json()
    rtype = req_enum(body, "request_type", REQUEST_TYPE)
    desc = req_str(body, "description")
    if b["booking_status"] == "RELEASED":
        raise ApiError("ERR_BOOKING_RELEASED", 409, "booking is RELEASED")
    obj = base_fields()
    obj.update({"booking_id": bid, "request_type": rtype, "description": desc,
                "request_status": "SUBMITTED", "appeal_count": 0})
    db["requests"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/bookings/<bid>/requests", methods=["GET"])
def list_requests(bid):
    auth(["HealthGrievanceOfficer", "Supervisor"])
    get_or_404("bookings", bid, "booking")
    items = [r for r in db["requests"].values() if r["booking_id"] == bid]
    return list_response(items)


def _request_transition(rid, allowed_from, new_status, inc_appeal=False):
    r = get_or_404("requests", rid, "request")
    if r["request_status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, f"request is not in {allowed_from}")
    r["request_status"] = new_status
    if inc_appeal:
        r["appeal_count"] += 1
    bump(r)
    return ok(public(r))


@app.route("/requests/<rid>/review", methods=["POST"])
def review_request(rid):
    auth(["HealthGrievanceOfficer"])
    return _request_transition(rid, ("SUBMITTED",), "UNDER_REVIEW")


@app.route("/requests/<rid>/deny", methods=["POST"])
def deny_request(rid):
    auth(["HealthGrievanceOfficer"])
    return _request_transition(rid, ("UNDER_REVIEW",), "DENIED")


@app.route("/requests/<rid>/appeal", methods=["POST"])
def appeal_request(rid):
    auth(["HealthGrievanceOfficer"])
    return _request_transition(rid, ("DENIED",), "UNDER_REVIEW", inc_appeal=True)


@app.route("/requests/<rid>/resolve", methods=["POST"])
def resolve_request(rid):
    auth(["HealthGrievanceOfficer"])
    return _request_transition(rid, ("UNDER_REVIEW",), "RESOLVED")


# --- Disciplinary ---
@app.route("/bookings/<bid>/infractions", methods=["POST"])
def report_infraction(bid):
    uid, role = auth(STAFF5)
    get_or_404("bookings", bid, "booking")
    body = body_json()
    itype = req_enum(body, "infraction_type", INFRACTION_TYPE)
    forfeit = req_int(body, "good_time_forfeit_days", minimum=0)
    obj = base_fields()
    obj.update({"booking_id": bid, "infraction_type": itype,
                "good_time_forfeit_days": forfeit, "reported_by_user_id": uid,
                "infraction_status": "REPORTED"})
    db["infractions"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/bookings/<bid>/infractions", methods=["GET"])
def list_infractions(bid):
    auth(["ClassificationOfficer", "Supervisor"])
    get_or_404("bookings", bid, "booking")
    items = [i for i in db["infractions"].values() if i["booking_id"] == bid]
    return list_response(items)


@app.route("/infractions/<iid>/uphold", methods=["POST"])
def uphold_infraction(iid):
    uid, role = auth(["Supervisor"])
    inf = get_or_404("infractions", iid, "infraction")
    # source-state (33)
    if inf["infraction_status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "infraction is not REPORTED")
    # segregation of duties (40)
    if uid == inf["reported_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "upholder must differ from reporter")
    inf["infraction_status"] = "UPHELD"
    bump(inf)
    b = db["bookings"].get(inf["booking_id"])
    if b is not None:
        b["total_forfeited_days"] += inf["good_time_forfeit_days"]
        recompute_good_time(b)
        bump(b)
    return ok(public(inf))


# --- Property ---
@app.route("/bookings/<bid>/property", methods=["POST"])
def create_property(bid):
    auth(["IntakeOfficer"])
    get_or_404("bookings", bid, "booking")
    body = body_json()
    desc = req_str(body, "description")
    category = req_enum(body, "category", PROPERTY_CATEGORY)
    obj = base_fields()
    obj.update({"booking_id": bid, "description": desc, "category": category,
                "property_status": "STORED"})
    db["property_items"][obj["id"]] = obj
    return ok(public(obj), status=201)


@app.route("/bookings/<bid>/property", methods=["GET"])
def list_property(bid):
    auth(["IntakeOfficer", "Supervisor"])
    get_or_404("bookings", bid, "booking")
    items = [p for p in db["property_items"].values() if p["booking_id"] == bid]
    return list_response(items)


@app.route("/property-items/<pid>/release", methods=["POST"])
def release_property(pid):
    auth(["IntakeOfficer"])
    p = get_or_404("property_items", pid, "property item")
    if p["property_status"] != "STORED":
        raise ApiError("ERR_INVALID_STATE", 409, "property item is not STORED")
    p["property_status"] = "RETURNED"
    bump(p)
    return ok(public(p))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
