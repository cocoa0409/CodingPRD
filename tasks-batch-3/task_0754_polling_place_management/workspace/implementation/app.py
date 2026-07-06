import os
import random
import string
import itertools
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_ROLES = {"ElectionAdmin", "PrecinctCaptain", "PollWorker", "CustodyOfficer", "SupportAgent"}

BASE_HOURLY_CENTS = 1825
LEAD_HOURLY_CENTS = 2450
OT_THRESHOLD_HOURS = Decimal(8)
OT_MULTIPLIER = Decimal("1.5")
TRAINING_STIPEND_CENTS = 5000

CUSTODY_EVENT_TYPES = {"ISSUE", "DISPATCH", "RECEIVE", "RETURN", "RECONCILE", "SEAL_BREAK", "VOID_ISSUE"}
EQUIPMENT_TYPES = {"SCANNER", "BMD", "EPOLLBOOK", "PRINTER"}
INCIDENT_CATEGORIES = {"EQUIPMENT", "STAFFING", "SECURITY", "ACCESSIBILITY", "OTHER"}

# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.elections = {}
        self.places = {}
        self.equipment = {}
        self.workers = {}
        self.assignments = {}
        self.shifts = {}
        self.kits = {}
        self.custody = {}
        self.provisionals = {}
        self.incidents = {}
        self.seq = itertools.count(1)
        self.clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


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
# Helpers: time / ids / formatting
# ---------------------------------------------------------------------------
def now_clock():
    return db.clock


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    import uuid
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_iso(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Response envelopes
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": fmt_ts(now_clock())}


def ok_object(data, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), code


def ok_array(items, limit, offset, total):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    return role, uid


# ---------------------------------------------------------------------------
# Body / pagination helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object.")
    return body


def require_present(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Missing required field: {key}")
    return body[key]


def require_str(body, key):
    val = require_present(body, key)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Field {key} must be a non-empty string.")
    return val


def require_int(body, key, minimum=None):
    val = require_present(body, key)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Field {key} must be an integer.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Field {key} must be >= {minimum}.")
    return val


def optional_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Field {key} must be a boolean.")
    return val


def optional_int(body, key, default=0, minimum=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Field {key} must be an integer.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 422, f"Field {key} must be >= {minimum}.")
    return val


def paginate(items):
    # items: list already sorted ascending by creation order
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
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_seq(values):
    return sorted(values, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Mutation helper
# ---------------------------------------------------------------------------
def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = fmt_ts(now_clock())


def new_common():
    ts = fmt_ts(now_clock())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(db.seq),
    }


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_hours(start_dt, end_dt):
    delta = end_dt - start_dt
    secs = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1000000)
    return (secs / Decimal(3600)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def shift_pay(hours, is_lead):
    rate = Decimal(LEAD_HOURLY_CENTS if is_lead else BASE_HOURLY_CENTS)
    regular = min(hours, OT_THRESHOLD_HOURS)
    overtime = hours - OT_THRESHOLD_HOURS
    if overtime < 0:
        overtime = Decimal(0)
    regular_pay = (regular * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    overtime_pay = (overtime * rate * OT_MULTIPLIER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(regular_pay + overtime_pay)


# ---------------------------------------------------------------------------
# Derived counts for a place
# ---------------------------------------------------------------------------
def count_active_slots(pid):
    return sum(1 for a in db.assignments.values()
               if a["polling_place_id"] == pid and a["status"] == "ACTIVE")


def count_provisional_cast(pid):
    return sum(1 for b in db.provisionals.values() if b["polling_place_id"] == pid)


def count_provisional_accepted(pid):
    return sum(1 for b in db.provisionals.values()
               if b["polling_place_id"] == pid and b["status"] == "ACCEPTED")


def sum_place_payroll(pid):
    return sum((s["gross_pay_cents"] or 0) for s in db.shifts.values()
               if s["polling_place_id"] == pid and s["status"] == "CHECKED_OUT")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
COMMON_OUT = ["id", "created_at", "updated_at", "version"]


def _common(entity):
    return {k: entity[k] for k in COMMON_OUT}


def ser_election(e):
    out = _common(e)
    out.update({
        "name": e["name"],
        "jurisdiction": e["jurisdiction"],
        "election_date": e["election_date"],
        "status": e["status"],
        "initial_ballot_stock": e["initial_ballot_stock"],
        "unallocated_ballot_stock": e["unallocated_ballot_stock"],
    })
    return out


def ser_place(p):
    pid = p["id"]
    slots_filled = count_active_slots(pid)
    out = _common(p)
    out.update({
        "election_id": p["election_id"],
        "name": p["name"],
        "address": p["address"],
        "min_workers_required": p["min_workers_required"],
        "staffing_capacity": p["staffing_capacity"],
        "station_capacity": p["station_capacity"],
        "wheelchair_accessible": p["wheelchair_accessible"],
        "accessible_parking": p["accessible_parking"],
        "ada_voting_stations": p["ada_voting_stations"],
        "readiness_posture": p["readiness_posture"],
        "slots_filled": slots_filled,
        "slots_open": p["staffing_capacity"] - slots_filled,
        "provisional_cast_count": count_provisional_cast(pid),
        "provisional_accepted_count": count_provisional_accepted(pid),
        "scanner_tally": p["scanner_tally"],
        "epollbook_checkins": p["epollbook_checkins"],
        "spoiled_count": p["spoiled_count"],
        "reconciliation_status": p["reconciliation_status"],
        "reconciliation_discrepancy": p["reconciliation_discrepancy"],
        "total_payroll_cents": sum_place_payroll(pid),
    })
    return out


def ser_equipment(e):
    out = _common(e)
    out.update({
        "equipment_type": e["equipment_type"],
        "serial_number": e["serial_number"],
        "status": e["status"],
        "polling_place_id": e["polling_place_id"],
    })
    return out


def ser_worker(w):
    out = _common(w)
    out.update({
        "full_name": w["full_name"],
        "email": w["email"],
        "phone": w["phone"],
        "training_status": w["training_status"],
        "accrued_payroll_cents": w["accrued_payroll_cents"],
        "stipend_paid": w["stipend_paid"],
    })
    return out


def ser_assignment(a):
    out = _common(a)
    out.update({
        "poll_worker_id": a["poll_worker_id"],
        "polling_place_id": a["polling_place_id"],
        "is_lead": a["is_lead"],
        "status": a["status"],
    })
    return out


def ser_shift(s):
    out = _common(s)
    out.update({
        "assignment_id": s["assignment_id"],
        "poll_worker_id": s["poll_worker_id"],
        "polling_place_id": s["polling_place_id"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "check_in_time": s["check_in_time"],
        "check_out_time": s["check_out_time"],
        "status": s["status"],
        "is_lead": s["is_lead"],
        "scheduled_hours": float(s["scheduled_hours"]),
        "scheduled_pay_cents": s["scheduled_pay_cents"],
        "actual_hours": float(s["actual_hours"]) if s["actual_hours"] is not None else None,
        "gross_pay_cents": s["gross_pay_cents"],
    })
    return out


def ser_kit(k):
    out = _common(k)
    out.update({
        "election_id": k["election_id"],
        "polling_place_id": k["polling_place_id"],
        "ballot_count": k["ballot_count"],
        "seal_number": k["seal_number"],
        "custody_state": k["custody_state"],
        "returned_ballot_count": k["returned_ballot_count"],
    })
    return out


def ser_custody(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "supply_kit_id": c["supply_kit_id"],
        "event_type": c["event_type"],
        "from_state": c["from_state"],
        "to_state": c["to_state"],
        "actor_role": c["actor_role"],
        "note": c["note"],
    }


def ser_provisional(b):
    out = _common(b)
    out.update({
        "polling_place_id": b["polling_place_id"],
        "voter_name": b["voter_name"],
        "reason": b["reason"],
        "status": b["status"],
    })
    return out


def ser_incident(i):
    out = _common(i)
    out.update({
        "polling_place_id": i["polling_place_id"],
        "equipment_unit_id": i["equipment_unit_id"],
        "category": i["category"],
        "description": i["description"],
        "severity": i["severity"],
        "status": i["status"],
        "resolution": i["resolution"],
    })
    return out


# ---------------------------------------------------------------------------
# Lookup helpers (raise 404)
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    ent = coll.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
    return ent


# ---------------------------------------------------------------------------
# Shared state-transition operations
# ---------------------------------------------------------------------------
def do_check_out_shift(shift):
    """Check out a CHECKED_IN shift: stamp clock, compute pay, accrue payroll.
    Bumps shift and worker versions; does NOT bump the place version (caller
    decides whether the place is being mutated in the same operation)."""
    shift["check_out_time"] = fmt_ts(now_clock())
    hours = compute_hours(shift["_check_in_dt"], now_clock())
    shift["actual_hours"] = hours
    gross = shift_pay(hours, shift["is_lead"])
    shift["gross_pay_cents"] = gross
    worker = db.workers.get(shift["poll_worker_id"])
    if worker is not None:
        worker["accrued_payroll_cents"] += gross
        if not worker["stipend_paid"]:
            worker["accrued_payroll_cents"] += TRAINING_STIPEND_CENTS
            worker["stipend_paid"] = True
        touch(worker)
    shift["status"] = "CHECKED_OUT"
    touch(shift)


def do_close_from_open(place):
    """Close an OPEN place, auto checking-out its CHECKED_IN shifts."""
    for s in db.shifts.values():
        if s["polling_place_id"] == place["id"] and s["status"] == "CHECKED_IN":
            do_check_out_shift(s)
    place["readiness_posture"] = "CLOSED"
    touch(place)


def force_suspend(place):
    if place["readiness_posture"] == "OPEN":
        place["readiness_posture"] = "SUSPENDED"
        touch(place)


def equipment_out_of_service(equipment):
    if equipment["status"] != "OPERATIONAL":
        return
    equipment["status"] = "OUT_OF_SERVICE"
    touch(equipment)
    pid = equipment["polling_place_id"]
    if pid and pid in db.places:
        force_suspend(db.places[pid])


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ===========================================================================
# ENDPOINTS
# ===========================================================================

# ---- Logical clock --------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    authenticate({"ElectionAdmin"})
    body = get_body()
    raw = require_present(body, "to_iso8601")
    try:
        dt = parse_iso(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "to_iso8601 must be a valid ISO 8601 instant.")
    db.clock = dt
    return ok_object({"current_utc": fmt_ts(dt)}, 200)


# ---- Elections ------------------------------------------------------------
@app.route("/elections", methods=["POST"])
def create_election():
    authenticate({"ElectionAdmin"})
    body = get_body()
    name = require_str(body, "name")
    jurisdiction = require_str(body, "jurisdiction")
    election_date = require_str(body, "election_date")
    initial_stock = require_int(body, "initial_ballot_stock", minimum=0)
    e = new_common()
    e.update({
        "name": name,
        "jurisdiction": jurisdiction,
        "election_date": election_date,
        "status": "PLANNING",
        "initial_ballot_stock": initial_stock,
        "unallocated_ballot_stock": initial_stock,
    })
    db.elections[e["id"]] = e
    return ok_object(ser_election(e), 201)


@app.route("/elections/<rid>", methods=["GET"])
def get_election(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_election(get_or_404(db.elections, rid)), 200)


@app.route("/elections/<rid>/open-voting", methods=["POST"])
def open_voting(rid):
    authenticate({"ElectionAdmin"})
    e = get_or_404(db.elections, rid)
    if e["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Election is not in PLANNING.")
    e["status"] = "VOTING_OPEN"
    touch(e)
    return ok_object(ser_election(e), 200)


@app.route("/elections/<rid>/close-voting", methods=["POST"])
def close_voting(rid):
    authenticate({"ElectionAdmin"})
    e = get_or_404(db.elections, rid)
    if e["status"] != "VOTING_OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Election is not in VOTING_OPEN.")
    e["status"] = "VOTING_CLOSED"
    # Cascade: close every child place still OPEN.
    for p in db.places.values():
        if p["election_id"] == rid and p["readiness_posture"] == "OPEN":
            do_close_from_open(p)
    touch(e)
    return ok_object(ser_election(e), 200)


# ---- Polling places -------------------------------------------------------
@app.route("/polling-places", methods=["POST"])
def create_place():
    authenticate({"ElectionAdmin"})
    body = get_body()
    election_id = require_str(body, "election_id")
    get_or_404(db.elections, election_id)
    name = require_str(body, "name")
    address = require_str(body, "address")
    min_workers = require_int(body, "min_workers_required", minimum=1)
    staffing = require_int(body, "staffing_capacity", minimum=1)
    station = require_int(body, "station_capacity", minimum=1)
    wheelchair = optional_bool(body, "wheelchair_accessible", False)
    parking = optional_bool(body, "accessible_parking", False)
    ada = optional_int(body, "ada_voting_stations", 0, minimum=0)
    p = new_common()
    p.update({
        "election_id": election_id,
        "name": name,
        "address": address,
        "min_workers_required": min_workers,
        "staffing_capacity": staffing,
        "station_capacity": station,
        "wheelchair_accessible": wheelchair,
        "accessible_parking": parking,
        "ada_voting_stations": ada,
        "readiness_posture": "SETUP",
        "scanner_tally": None,
        "epollbook_checkins": None,
        "spoiled_count": 0,
        "reconciliation_status": "UNRECONCILED",
        "reconciliation_discrepancy": None,
    })
    db.places[p["id"]] = p
    return ok_object(ser_place(p), 201)


@app.route("/polling-places/<rid>", methods=["GET"])
def get_place(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_place(get_or_404(db.places, rid)), 200)


@app.route("/polling-places", methods=["GET"])
def list_places():
    authenticate(ALL_ROLES)
    election_id = request.args.get("election_id")
    items = [p for p in db.places.values()
             if election_id is None or p["election_id"] == election_id]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_place(p) for p in page], limit, offset, total)


def _check_open_resume_safety(place):
    """Shared safety checks for open/resume: no compromised kit, all equipment operational."""
    for k in db.kits.values():
        if k["polling_place_id"] == place["id"] and k["custody_state"] == "COMPROMISED":
            raise ApiError("ERR_KIT_COMPROMISED", 409, "A supply kit for this place is COMPROMISED.")
    for eq in db.equipment.values():
        if eq["polling_place_id"] == place["id"] and eq["status"] == "OUT_OF_SERVICE":
            raise ApiError("ERR_EQUIPMENT_NOT_OPERATIONAL", 409,
                           "Equipment at this place is OUT_OF_SERVICE.")


@app.route("/polling-places/<rid>/open", methods=["POST"])
def open_place(rid):
    authenticate({"PrecinctCaptain"})
    p = get_or_404(db.places, rid)
    if p["readiness_posture"] != "SETUP":
        raise ApiError("ERR_INVALID_STATE", 409, "Place is not in SETUP.")
    election = db.elections.get(p["election_id"])
    if election is None or election["status"] != "VOTING_OPEN":
        raise ApiError("ERR_VOTING_NOT_OPEN", 409, "Election voting window is not open.")
    # kit compromised check (priority 5)
    for k in db.kits.values():
        if k["polling_place_id"] == rid and k["custody_state"] == "COMPROMISED":
            raise ApiError("ERR_KIT_COMPROMISED", 409, "A supply kit for this place is COMPROMISED.")
    # equipment operational + at least one kit AT_PLACE (priority 6)
    for eq in db.equipment.values():
        if eq["polling_place_id"] == rid and eq["status"] == "OUT_OF_SERVICE":
            raise ApiError("ERR_EQUIPMENT_NOT_OPERATIONAL", 409,
                           "Equipment at this place is OUT_OF_SERVICE.")
    if not any(k["polling_place_id"] == rid and k["custody_state"] == "AT_PLACE"
               for k in db.kits.values()):
        raise ApiError("ERR_EQUIPMENT_NOT_OPERATIONAL", 409,
                       "No supply kit is AT_PLACE.")
    # understaffed (priority 12)
    if count_active_slots(rid) < p["min_workers_required"]:
        raise ApiError("ERR_UNDERSTAFFED", 422, "Not enough active workers to open.")
    p["readiness_posture"] = "OPEN"
    touch(p)
    return ok_object(ser_place(p), 200)


@app.route("/polling-places/<rid>/suspend", methods=["POST"])
def suspend_place(rid):
    authenticate({"PrecinctCaptain"})
    p = get_or_404(db.places, rid)
    if p["readiness_posture"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Place is not OPEN.")
    p["readiness_posture"] = "SUSPENDED"
    touch(p)
    return ok_object(ser_place(p), 200)


@app.route("/polling-places/<rid>/resume", methods=["POST"])
def resume_place(rid):
    authenticate({"PrecinctCaptain"})
    p = get_or_404(db.places, rid)
    if p["readiness_posture"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Place is not SUSPENDED.")
    _check_open_resume_safety(p)
    p["readiness_posture"] = "OPEN"
    touch(p)
    return ok_object(ser_place(p), 200)


@app.route("/polling-places/<rid>/close", methods=["POST"])
def close_place(rid):
    authenticate({"PrecinctCaptain"})
    p = get_or_404(db.places, rid)
    posture = p["readiness_posture"]
    if posture == "OPEN":
        do_close_from_open(p)
    elif posture == "SUSPENDED":
        p["readiness_posture"] = "CLOSED"
        touch(p)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Place cannot be closed from its current posture.")
    return ok_object(ser_place(p), 200)


@app.route("/polling-places/<rid>/reconcile", methods=["POST"])
def reconcile_place(rid):
    authenticate({"PrecinctCaptain"})
    p = get_or_404(db.places, rid)
    if p["readiness_posture"] not in ("CLOSED", "RECONCILED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Place must be CLOSED or RECONCILED to reconcile.")
    body = get_body()
    scanner_tally = require_int(body, "scanner_tally")
    epollbook_checkins = require_int(body, "epollbook_checkins")
    spoiled_count = optional_int(body, "spoiled_count", 0)
    if scanner_tally < 0 or epollbook_checkins < 0 or spoiled_count < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Reconciliation counts must be non-negative.")
    expected_version = require_int(body, "expected_polling_place_version")
    if expected_version != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_polling_place_version is stale.")
    accepted = count_provisional_accepted(rid)
    discrepancy = (scanner_tally + accepted) - epollbook_checkins
    p["scanner_tally"] = scanner_tally
    p["epollbook_checkins"] = epollbook_checkins
    p["spoiled_count"] = spoiled_count
    p["reconciliation_discrepancy"] = discrepancy
    p["reconciliation_status"] = "BALANCED" if discrepancy == 0 else "MISMATCH"
    p["readiness_posture"] = "RECONCILED"
    touch(p)
    return ok_object(ser_place(p), 200)


# ---- Equipment ------------------------------------------------------------
@app.route("/equipment", methods=["POST"])
def create_equipment():
    authenticate({"ElectionAdmin"})
    body = get_body()
    eq_type = require_str(body, "equipment_type")
    if eq_type not in EQUIPMENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Invalid equipment_type.")
    serial = require_str(body, "serial_number")
    eq = new_common()
    eq.update({
        "equipment_type": eq_type,
        "serial_number": serial,
        "status": "IN_WAREHOUSE",
        "polling_place_id": None,
    })
    db.equipment[eq["id"]] = eq
    return ok_object(ser_equipment(eq), 201)


@app.route("/equipment/<rid>", methods=["GET"])
def get_equipment(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_equipment(get_or_404(db.equipment, rid)), 200)


@app.route("/equipment", methods=["GET"])
def list_equipment():
    authenticate(ALL_ROLES)
    pid = request.args.get("polling_place_id")
    items = [e for e in db.equipment.values()
             if pid is None or e["polling_place_id"] == pid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_equipment(e) for e in page], limit, offset, total)


@app.route("/equipment/<rid>/deploy", methods=["POST"])
def deploy_equipment(rid):
    authenticate({"ElectionAdmin"})
    eq = get_or_404(db.equipment, rid)
    body = get_body()
    pid = require_str(body, "polling_place_id")
    get_or_404(db.places, pid)
    if eq["status"] != "IN_WAREHOUSE":
        raise ApiError("ERR_INVALID_STATE", 409, "Equipment is not IN_WAREHOUSE.")
    eq["polling_place_id"] = pid
    eq["status"] = "OPERATIONAL"
    touch(eq)
    return ok_object(ser_equipment(eq), 200)


# ---- Poll workers ---------------------------------------------------------
@app.route("/poll-workers", methods=["POST"])
def create_worker():
    authenticate({"ElectionAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = body.get("phone")
    if phone is not None and not isinstance(phone, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "phone must be a string.")
    w = new_common()
    w.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "training_status": "PENDING",
        "accrued_payroll_cents": 0,
        "stipend_paid": False,
    })
    db.workers[w["id"]] = w
    return ok_object(ser_worker(w), 201)


@app.route("/poll-workers/<rid>", methods=["GET"])
def get_worker(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_worker(get_or_404(db.workers, rid)), 200)


@app.route("/poll-workers/<rid>/complete-training", methods=["POST"])
def complete_training(rid):
    authenticate({"ElectionAdmin"})
    w = get_or_404(db.workers, rid)
    if w["training_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Worker is not PENDING.")
    w["training_status"] = "CERTIFIED"
    touch(w)
    return ok_object(ser_worker(w), 200)


# ---- Assignments ----------------------------------------------------------
@app.route("/assignments", methods=["POST"])
def create_assignment():
    authenticate({"PrecinctCaptain", "ElectionAdmin"})
    body = get_body()
    worker_id = require_str(body, "poll_worker_id")
    place_id = require_str(body, "polling_place_id")
    get_or_404(db.workers, worker_id)
    get_or_404(db.places, place_id)
    is_lead = optional_bool(body, "is_lead", False)
    a = new_common()
    a.update({
        "poll_worker_id": worker_id,
        "polling_place_id": place_id,
        "is_lead": is_lead,
        "status": "PROPOSED",
    })
    db.assignments[a["id"]] = a
    return ok_object(ser_assignment(a), 201)


@app.route("/assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_assignment(get_or_404(db.assignments, rid)), 200)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    authenticate(ALL_ROLES)
    worker_id = request.args.get("poll_worker_id")
    place_id = request.args.get("polling_place_id")
    items = [a for a in db.assignments.values()
             if (worker_id is None or a["poll_worker_id"] == worker_id)
             and (place_id is None or a["polling_place_id"] == place_id)]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_assignment(a) for a in page], limit, offset, total)


@app.route("/assignments/<rid>/activate", methods=["POST"])
def activate_assignment(rid):
    authenticate({"PrecinctCaptain", "ElectionAdmin"})
    a = get_or_404(db.assignments, rid)
    if a["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not PROPOSED.")
    worker = db.workers.get(a["poll_worker_id"])
    if worker is None or worker["training_status"] != "CERTIFIED":
        raise ApiError("ERR_WORKER_NOT_CERTIFIED", 422, "Worker is not CERTIFIED.")
    place = db.places.get(a["polling_place_id"])
    slots_open = place["staffing_capacity"] - count_active_slots(place["id"])
    if slots_open < 1:
        raise ApiError("ERR_NO_OPEN_SLOTS", 422, "No open staffing slot at the place.")
    a["status"] = "ACTIVE"
    touch(a)
    touch(place)  # slots_filled / slots_open changed
    return ok_object(ser_assignment(a), 200)


@app.route("/assignments/<rid>/withdraw", methods=["POST"])
def withdraw_assignment(rid):
    authenticate({"PrecinctCaptain", "ElectionAdmin"})
    a = get_or_404(db.assignments, rid)
    if a["status"] not in ("PROPOSED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment cannot be withdrawn from its state.")
    was_active = a["status"] == "ACTIVE"
    a["status"] = "WITHDRAWN"
    touch(a)
    if was_active:
        place = db.places.get(a["polling_place_id"])
        if place is not None:
            touch(place)  # slot released
    return ok_object(ser_assignment(a), 200)


# ---- Shifts ---------------------------------------------------------------
@app.route("/shifts", methods=["POST"])
def create_shift():
    authenticate({"PrecinctCaptain", "ElectionAdmin"})
    body = get_body()
    assignment_id = require_str(body, "assignment_id")
    assignment = get_or_404(db.assignments, assignment_id)
    start_raw = require_str(body, "scheduled_start")
    end_raw = require_str(body, "scheduled_end")
    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Invalid schedule timestamps.")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_REQUEST", 422, "scheduled_end must be after scheduled_start.")
    worker_id = assignment["poll_worker_id"]
    place_id = assignment["polling_place_id"]
    # per-worker overlap (priority 8) against any other shift of the same worker
    for s in db.shifts.values():
        if s["poll_worker_id"] == worker_id and overlaps(start_dt, end_dt, s["_start_dt"], s["_end_dt"]):
            raise ApiError("ERR_WORKER_SHIFT_OVERLAP", 409, "Worker already has an overlapping shift.")
    # place capacity (priority 9)
    place = db.places.get(place_id)
    overlap_count = sum(1 for s in db.shifts.values()
                        if s["polling_place_id"] == place_id
                        and overlaps(start_dt, end_dt, s["_start_dt"], s["_end_dt"]))
    if place is not None and overlap_count >= place["station_capacity"]:
        raise ApiError("ERR_PLACE_CAPACITY_EXCEEDED", 409, "Place station capacity exceeded.")
    is_lead = assignment["is_lead"]
    scheduled_hours = compute_hours(start_dt, end_dt)
    scheduled_pay = shift_pay(scheduled_hours, is_lead)
    s = new_common()
    s.update({
        "assignment_id": assignment_id,
        "poll_worker_id": worker_id,
        "polling_place_id": place_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "check_in_time": None,
        "check_out_time": None,
        "status": "SCHEDULED",
        "is_lead": is_lead,
        "scheduled_hours": scheduled_hours,
        "scheduled_pay_cents": scheduled_pay,
        "actual_hours": None,
        "gross_pay_cents": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_check_in_dt": None,
    })
    db.shifts[s["id"]] = s
    return ok_object(ser_shift(s), 201)


@app.route("/shifts/<rid>", methods=["GET"])
def get_shift(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_shift(get_or_404(db.shifts, rid)), 200)


@app.route("/shifts", methods=["GET"])
def list_shifts():
    authenticate(ALL_ROLES)
    assignment_id = request.args.get("assignment_id")
    worker_id = request.args.get("poll_worker_id")
    place_id = request.args.get("polling_place_id")
    items = [s for s in db.shifts.values()
             if (assignment_id is None or s["assignment_id"] == assignment_id)
             and (worker_id is None or s["poll_worker_id"] == worker_id)
             and (place_id is None or s["polling_place_id"] == place_id)]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_shift(s) for s in page], limit, offset, total)


@app.route("/shifts/<rid>/check-in", methods=["POST"])
def check_in_shift(rid):
    authenticate({"PrecinctCaptain", "PollWorker"})
    s = get_or_404(db.shifts, rid)
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift is not SCHEDULED.")
    worker = db.workers.get(s["poll_worker_id"])
    if worker is None or worker["training_status"] != "CERTIFIED":
        raise ApiError("ERR_WORKER_NOT_CERTIFIED", 422, "Worker is not CERTIFIED.")
    assignment = db.assignments.get(s["assignment_id"])
    if assignment is None or assignment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Parent assignment is not ACTIVE.")
    place = db.places.get(s["polling_place_id"])
    if place is None or place["readiness_posture"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Owning place is not OPEN.")
    # per-worker overlap vs other CHECKED_IN or SCHEDULED shifts of the worker
    for other in db.shifts.values():
        if other["id"] == s["id"]:
            continue
        if other["poll_worker_id"] != s["poll_worker_id"]:
            continue
        if other["status"] not in ("CHECKED_IN", "SCHEDULED"):
            continue
        if overlaps(s["_start_dt"], s["_end_dt"], other["_start_dt"], other["_end_dt"]):
            raise ApiError("ERR_WORKER_SHIFT_OVERLAP", 409, "Worker has an overlapping shift.")
    s["check_in_time"] = fmt_ts(now_clock())
    s["_check_in_dt"] = now_clock()
    s["status"] = "CHECKED_IN"
    touch(s)
    return ok_object(ser_shift(s), 200)


@app.route("/shifts/<rid>/check-out", methods=["POST"])
def check_out_shift(rid):
    authenticate({"PrecinctCaptain", "PollWorker"})
    s = get_or_404(db.shifts, rid)
    if s["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Shift is not CHECKED_IN.")
    do_check_out_shift(s)
    place = db.places.get(s["polling_place_id"])
    if place is not None:
        touch(place)  # total_payroll_cents changed
    return ok_object(ser_shift(s), 200)


# ---- Supply kits ----------------------------------------------------------
@app.route("/supply-kits", methods=["POST"])
def create_kit():
    authenticate({"CustodyOfficer"})
    body = get_body()
    election_id = require_str(body, "election_id")
    get_or_404(db.elections, election_id)
    ballot_count = require_int(body, "ballot_count", minimum=1)
    seal_number = require_str(body, "seal_number")
    k = new_common()
    k.update({
        "election_id": election_id,
        "polling_place_id": None,
        "ballot_count": ballot_count,
        "seal_number": seal_number,
        "custody_state": "PREPARED",
        "returned_ballot_count": None,
    })
    db.kits[k["id"]] = k
    return ok_object(ser_kit(k), 201)


@app.route("/supply-kits/<rid>", methods=["GET"])
def get_kit(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_kit(get_or_404(db.kits, rid)), 200)


@app.route("/supply-kits", methods=["GET"])
def list_kits():
    authenticate(ALL_ROLES)
    election_id = request.args.get("election_id")
    place_id = request.args.get("polling_place_id")
    items = [k for k in db.kits.values()
             if (election_id is None or k["election_id"] == election_id)
             and (place_id is None or k["polling_place_id"] == place_id)]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_kit(k) for k in page], limit, offset, total)


CUSTODY_TRANSITIONS = {
    "ISSUE": ("PREPARED", "ISSUED"),
    "VOID_ISSUE": ("ISSUED", "PREPARED"),
    "DISPATCH": ("ISSUED", "IN_TRANSIT"),
    "RECEIVE": ("IN_TRANSIT", "AT_PLACE"),
    "RETURN": ("AT_PLACE", "RETURN_PENDING"),
    "RECONCILE": ("RETURN_PENDING", "RECONCILED"),
}
SEAL_BREAK_FROM = {"ISSUED", "IN_TRANSIT", "AT_PLACE"}


@app.route("/supply-kits/<rid>/custody-events", methods=["POST"])
def create_custody_event(rid):
    role, _uid = authenticate({"CustodyOfficer"})
    kit = get_or_404(db.kits, rid)
    body = get_body()
    event_type = require_present(body, "event_type")
    if not isinstance(event_type, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "event_type must be a string.")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "note must be a string.")
    current = kit["custody_state"]

    # Resolve a provided polling_place_id FK first (existence, priority 3)
    provided_place = None
    if body.get("polling_place_id") is not None:
        provided_place = get_or_404(db.places, body["polling_place_id"])

    if event_type == "SEAL_BREAK":
        if current not in SEAL_BREAK_FROM:
            raise ApiError("ERR_INVALID_CUSTODY_TRANSITION", 422,
                           "SEAL_BREAK not valid from current custody_state.")
        from_state = current
        kit["custody_state"] = "COMPROMISED"
        to_state = "COMPROMISED"
        _append_custody(kit, event_type, from_state, to_state, role, note)
        touch(kit)
        pid = kit["polling_place_id"]
        if pid and pid in db.places:
            force_suspend(db.places[pid])
        return ok_object(ser_custody(_last_event(kit["id"])), 201)

    if event_type not in CUSTODY_TRANSITIONS:
        raise ApiError("ERR_INVALID_CUSTODY_TRANSITION", 422, "Unknown custody event_type.")

    required_from, to_state = CUSTODY_TRANSITIONS[event_type]
    if current != required_from:
        raise ApiError("ERR_INVALID_CUSTODY_TRANSITION", 422,
                       "event_type not valid from current custody_state.")

    if event_type == "RECEIVE" and provided_place is None:
        raise ApiError("ERR_INVALID_CUSTODY_TRANSITION", 422,
                       "RECEIVE requires polling_place_id.")

    if event_type == "ISSUE":
        election = db.elections.get(kit["election_id"])
        if election is None or election["unallocated_ballot_stock"] < kit["ballot_count"]:
            raise ApiError("ERR_INSUFFICIENT_BALLOT_STOCK", 422, "Insufficient ballot stock.")

    from_state = current
    kit["custody_state"] = to_state

    if event_type == "ISSUE":
        election = db.elections[kit["election_id"]]
        election["unallocated_ballot_stock"] -= kit["ballot_count"]
        touch(election)
    elif event_type == "VOID_ISSUE":
        election = db.elections.get(kit["election_id"])
        if election is not None:
            election["unallocated_ballot_stock"] += kit["ballot_count"]
            touch(election)
    elif event_type == "RECEIVE":
        kit["polling_place_id"] = provided_place["id"]
    elif event_type == "RECONCILE":
        rbc = body.get("returned_ballot_count")
        if rbc is not None:
            if isinstance(rbc, bool) or not isinstance(rbc, int) or rbc < 0:
                raise ApiError("ERR_INVALID_REQUEST", 422, "returned_ballot_count must be a non-negative integer.")
        kit["returned_ballot_count"] = rbc

    _append_custody(kit, event_type, from_state, to_state, role, note)
    touch(kit)
    return ok_object(ser_custody(_last_event(kit["id"])), 201)


def _append_custody(kit, event_type, from_state, to_state, role, note):
    ts = fmt_ts(now_clock())
    ev = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next(db.seq),
        "supply_kit_id": kit["id"],
        "event_type": event_type,
        "from_state": from_state,
        "to_state": to_state,
        "actor_role": role,
        "note": note,
    }
    db.custody[ev["id"]] = ev
    return ev


def _last_event(kit_id):
    evs = [e for e in db.custody.values() if e["supply_kit_id"] == kit_id]
    return max(evs, key=lambda e: e["_seq"])


@app.route("/supply-kits/<rid>/custody-events", methods=["GET"])
def list_custody_events(rid):
    authenticate(ALL_ROLES)
    get_or_404(db.kits, rid)
    items = [e for e in db.custody.values() if e["supply_kit_id"] == rid]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_custody(e) for e in page], limit, offset, total)


# ---- Provisional ballots --------------------------------------------------
@app.route("/provisional-ballots", methods=["POST"])
def cast_provisional():
    authenticate({"PrecinctCaptain", "PollWorker"})
    body = get_body()
    place_id = require_str(body, "polling_place_id")
    place = get_or_404(db.places, place_id)
    if place["readiness_posture"] != "OPEN":
        raise ApiError("ERR_VOTING_NOT_OPEN", 409, "Place is not OPEN.")
    voter_name = require_str(body, "voter_name")
    reason = require_str(body, "reason")
    b = new_common()
    b.update({
        "polling_place_id": place_id,
        "voter_name": voter_name,
        "reason": reason,
        "status": "CAST",
    })
    db.provisionals[b["id"]] = b
    touch(place)  # provisional_cast_count changed
    return ok_object(ser_provisional(b), 201)


@app.route("/provisional-ballots/<rid>", methods=["GET"])
def get_provisional(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_provisional(get_or_404(db.provisionals, rid)), 200)


@app.route("/provisional-ballots", methods=["GET"])
def list_provisionals():
    authenticate(ALL_ROLES)
    place_id = request.args.get("polling_place_id")
    items = [b for b in db.provisionals.values()
             if place_id is None or b["polling_place_id"] == place_id]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_provisional(b) for b in page], limit, offset, total)


@app.route("/provisional-ballots/<rid>/adjudicate", methods=["POST"])
def adjudicate_provisional(rid):
    authenticate({"PrecinctCaptain"})
    b = get_or_404(db.provisionals, rid)
    if b["status"] != "CAST":
        raise ApiError("ERR_INVALID_STATE", 409, "Ballot is not CAST.")
    body = get_body()
    decision = require_present(body, "decision")
    if decision not in ("ACCEPT", "REJECT"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "decision must be ACCEPT or REJECT.")
    if decision == "ACCEPT":
        b["status"] = "ACCEPTED"
        touch(b)
        place = db.places.get(b["polling_place_id"])
        if place is not None:
            touch(place)  # provisional_accepted_count changed
    else:
        b["status"] = "REJECTED"
        touch(b)
    return ok_object(ser_provisional(b), 200)


# ---- Incidents ------------------------------------------------------------
@app.route("/incidents", methods=["POST"])
def create_incident():
    authenticate({"SupportAgent", "PrecinctCaptain"})
    body = get_body()
    place_id = require_str(body, "polling_place_id")
    get_or_404(db.places, place_id)
    equipment_unit_id = body.get("equipment_unit_id")
    if equipment_unit_id is not None:
        if not isinstance(equipment_unit_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 422, "equipment_unit_id must be a string.")
        get_or_404(db.equipment, equipment_unit_id)
    category = require_str(body, "category")
    if category not in INCIDENT_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Invalid category.")
    description = require_str(body, "description")
    i = new_common()
    i.update({
        "polling_place_id": place_id,
        "equipment_unit_id": equipment_unit_id,
        "category": category,
        "description": description,
        "severity": "LOW",
        "status": "OPEN",
        "resolution": None,
    })
    db.incidents[i["id"]] = i
    return ok_object(ser_incident(i), 201)


@app.route("/incidents/<rid>", methods=["GET"])
def get_incident(rid):
    authenticate(ALL_ROLES)
    return ok_object(ser_incident(get_or_404(db.incidents, rid)), 200)


@app.route("/incidents", methods=["GET"])
def list_incidents():
    authenticate(ALL_ROLES)
    place_id = request.args.get("polling_place_id")
    equipment_unit_id = request.args.get("equipment_unit_id")
    items = [i for i in db.incidents.values()
             if (place_id is None or i["polling_place_id"] == place_id)
             and (equipment_unit_id is None or i["equipment_unit_id"] == equipment_unit_id)]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_array([ser_incident(i) for i in page], limit, offset, total)


@app.route("/incidents/<rid>/acknowledge", methods=["POST"])
def acknowledge_incident(rid):
    authenticate({"SupportAgent"})
    i = get_or_404(db.incidents, rid)
    if i["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Incident is not OPEN.")
    i["status"] = "ACKNOWLEDGED"
    touch(i)
    return ok_object(ser_incident(i), 200)


@app.route("/incidents/<rid>/escalate", methods=["POST"])
def escalate_incident(rid):
    authenticate({"SupportAgent"})
    i = get_or_404(db.incidents, rid)
    if i["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Incident cannot be escalated from its state.")
    i["status"] = "ESCALATED"
    i["severity"] = "CRITICAL"
    if i["category"] == "EQUIPMENT" and i["equipment_unit_id"]:
        eq = db.equipment.get(i["equipment_unit_id"])
        if eq is not None:
            equipment_out_of_service(eq)
    touch(i)
    return ok_object(ser_incident(i), 200)


@app.route("/incidents/<rid>/resolve", methods=["POST"])
def resolve_incident(rid):
    authenticate({"SupportAgent"})
    i = get_or_404(db.incidents, rid)
    if i["status"] not in ("ACKNOWLEDGED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Incident cannot be resolved from its state.")
    body = get_body()
    resolution = require_str(body, "resolution")
    i["resolution"] = resolution
    i["status"] = "RESOLVED"
    touch(i)
    return ok_object(ser_incident(i), 200)


# ---- Health ---------------------------------------------------------------
@app.route("/_health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
