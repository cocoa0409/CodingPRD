"""Animal-Control & Field-Services Dispatch API.

Single-file Flask implementation. In-memory storage only (dicts keyed by id);
all state is wiped on every process start (the harness relaunches start.sh
before every test). No entity seeding at startup.
"""

import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Dispatcher", "FieldOfficer", "Supervisor", "HealthDeptLiaison"}

ZONES = {"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"}
ANIMAL_TYPES = {"DOG", "CAT", "WILDLIFE", "LIVESTOCK", "OTHER"}
COMPLAINT_TYPES = {"STRAY", "BITE", "CRUELTY", "DANGEROUS_DOG", "NOISE", "OTHER"}
CASE_TYPES = {"STRAY", "BITE", "CRUELTY", "DANGEROUS_DOG"}
HOLD_TYPES = {"HOME_QUARANTINE", "FACILITY_QUARANTINE"}
FIELD_OUTCOMES = {"RESOLVED_ON_SCENE", "ANIMAL_IMPOUNDED", "CASE_OPENED",
                  "GONE_ON_ARRIVAL", "REFERRED"}
NOTE_TYPES = {"OBSERVATION", "EVIDENCE", "WITNESS", "FOLLOWUP"}
VIOLATION_CODES = {"UNLICENSED", "LEASH", "DANGEROUS", "BITE", "CRUELTY"}
DISPOSITIONS = {"REDEEMED", "ADOPTED", "RELEASED", "EUTHANIZED"}
RESOLUTIONS = {"SUBSTANTIATED", "UNFOUNDED"}

SEVERITY_BASE = {"BITE": 50, "DANGEROUS_DOG": 40, "CRUELTY": 35,
                 "STRAY": 15, "NOISE": 5, "OTHER": 10}
ANIMAL_MULT = {"WILDLIFE": "1.5", "DOG": "1.2", "LIVESTOCK": "1.1",
               "CAT": "1.0", "OTHER": "1.0"}
REPEAT_STEP = 5
REPEAT_CAP = 20
VULNERABLE_BONUS = 15
P1_THRESHOLD = 60
P2_THRESHOLD = 30

VIOLATION_FINE = {"UNLICENSED": 50, "LEASH": 75, "DANGEROUS": 250,
                  "BITE": 300, "CRUELTY": 500}

TYPE_WEIGHT = {"BITE": 40, "DANGEROUS_DOG": 35, "CRUELTY": 30, "STRAY": 10}
SEV_FACTOR = "0.5"
SUBSTANTIATION_BONUS = 20
RISK_MIN = 0
RISK_MAX = 100

DAILY_RATE = "12.50"
INTAKE_FEE = "15.00"
UNLICENSED_SURCHARGE = "22.75"
TAX_RATE = "1.075"
SECONDS_PER_DAY = 86400

BITE_DAYS = 10
DANGEROUS_DOG_DAYS = 14

# Buffered-adjacency window for officer schedule conflicts. Not pinned to a
# concrete number in the spec; 30 minutes is the operating assumption.
BUFFER_MINUTES = 30

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "complaints": {},
    "officers": {},
    "kennels": {},
    "dispatches": {},
    "cases": {},
    "notes": {},
    "quarantine_holds": {},
    "impounds": {},
    "citations": {},
    "rabies_reports": {},
}

_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# Logical clock — resets to the fixed default on every process start.
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def logical_now():
    return CLOCK["now"]


def real_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def invalid_request(msg="Invalid request payload"):
    raise ApiError("ERR_INVALID_REQUEST", 422, msg)


# ---------------------------------------------------------------------------
# Datetime & money helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp(value, lo, hi):
    if value < lo:
        return Decimal(lo)
    if value > hi:
        return Decimal(hi)
    return value


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(real_now()),
    }


def resp_object(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def resp_array(items, limit, offset, total):
    meta = make_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def stamp_new(rec, common=True):
    rec["id"] = str(uuid.uuid4())
    rec["_seq"] = next_seq()
    now = real_now()
    rec["created_at"] = now
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = real_now()
    rec["version"] += 1


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unknown authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> 404)
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "officers": "ERR_OFFICER_NOT_FOUND",
    "kennels": "ERR_KENNEL_NOT_FOUND",
    "dispatches": "ERR_DISPATCH_NOT_FOUND",
    "cases": "ERR_CASE_NOT_FOUND",
    "quarantine_holds": "ERR_QUARANTINE_HOLD_NOT_FOUND",
    "impounds": "ERR_IMPOUND_NOT_FOUND",
    "citations": "ERR_CITATION_NOT_FOUND",
    "rabies_reports": "ERR_RABIES_REPORT_NOT_FOUND",
}


def get_or_404(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise ApiError(NOT_FOUND[collection], 404,
                       f"{collection[:-1]} not found")
    return rec


# ---------------------------------------------------------------------------
# Body / integrity helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        invalid_request(f"Missing or invalid field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        invalid_request(f"Missing or invalid enum: {field}")
    return v


def req_dt(body, field):
    v = body.get(field)
    dt = parse_dt(v)
    if dt is None:
        invalid_request(f"Missing or unparseable datetime: {field}")
    return dt


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        invalid_request(f"Invalid boolean: {field}")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        invalid_request(f"Invalid integer: {field}")
    return v


def paginate(items):
    def _int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _int("limit", 10)
    offset = _int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------
@app.post("/dispatch/complaints")
def create_complaint():
    _, role = authenticate()
    authorize(role, {"Dispatcher", "Supervisor"})
    body = get_body()

    reporter_name = req_str(body, "reporter_name")
    reporter_phone = req_str(body, "reporter_phone")
    zone = req_enum(body, "zone", ZONES)
    animal_type = req_enum(body, "animal_type", ANIMAL_TYPES)
    complaint_type = req_enum(body, "complaint_type", COMPLAINT_TYPES)
    vulnerable = opt_bool(body, "involves_vulnerable_victim", False)
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        invalid_request("Invalid description")

    # severity score
    base = Decimal(SEVERITY_BASE[complaint_type])
    mult = Decimal(ANIMAL_MULT[animal_type])
    open_same_zone = sum(
        1 for c in db["complaints"].values()
        if c["zone"] == zone and c["status"] in ("NEW", "DISPATCHED")
    )
    repeat_bonus = min(open_same_zone * REPEAT_STEP, REPEAT_CAP)
    vuln_bonus = VULNERABLE_BONUS if vulnerable else 0
    score = q2(base * mult + Decimal(repeat_bonus) + Decimal(vuln_bonus))
    score_f = float(score)
    if score_f >= P1_THRESHOLD:
        priority = "P1"
    elif score_f >= P2_THRESHOLD:
        priority = "P2"
    else:
        priority = "P3"

    rec = {
        "reporter_name": reporter_name,
        "reporter_phone": reporter_phone,
        "zone": zone,
        "animal_type": animal_type,
        "complaint_type": complaint_type,
        "involves_vulnerable_victim": vulnerable,
        "description": description,
        "severity_score": score_f,
        "priority": priority,
        "status": "NEW",
    }
    stamp_new(rec)
    db["complaints"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/complaints/<rid>")
def get_complaint(rid):
    _, role = authenticate()
    authorize(role, {"Dispatcher", "FieldOfficer", "Supervisor",
                     "HealthDeptLiaison"})
    rec = get_or_404("complaints", rid)
    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# Officer
# ---------------------------------------------------------------------------
@app.post("/dispatch/officers")
def create_officer():
    _, role = authenticate()
    authorize(role, {"Supervisor"})
    body = get_body()

    name = req_str(body, "name")
    badge_number = req_str(body, "badge_number")
    territory_zone = req_enum(body, "territory_zone", ZONES)
    shift_start = req_dt(body, "shift_start_at")
    shift_end = req_dt(body, "shift_end_at")
    max_daily = opt_int(body, "max_daily_dispatches", 8)
    if max_daily is None:
        max_daily = 8

    rec = {
        "name": name,
        "badge_number": badge_number,
        "territory_zone": territory_zone,
        "shift_start_at": shift_start,
        "shift_end_at": shift_end,
        "max_daily_dispatches": max_daily,
        "active_dispatch_count": 0,
    }
    stamp_new(rec)
    db["officers"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/officers/<rid>")
def get_officer(rid):
    _, role = authenticate()
    authorize(role, {"Dispatcher", "FieldOfficer", "Supervisor"})
    rec = get_or_404("officers", rid)
    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# Kennel
# ---------------------------------------------------------------------------
@app.post("/dispatch/kennels")
def create_kennel():
    _, role = authenticate()
    authorize(role, {"Supervisor"})
    body = get_body()

    code = req_str(body, "code")
    facility_zone = req_enum(body, "facility_zone", ZONES)

    rec = {
        "code": code,
        "facility_zone": facility_zone,
        "occupied_slots": 0,
    }
    stamp_new(rec)
    db["kennels"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/kennels/<rid>")
def get_kennel(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("kennels", rid)
    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
@app.post("/dispatch/dispatches")
def create_dispatch():
    _, role = authenticate()
    authorize(role, {"Dispatcher", "Supervisor"})
    body = get_body()

    # existence (left-to-right): complaint then officer
    complaint_id = body.get("complaint_id")
    officer_id = body.get("officer_id")
    complaint = None
    officer = None
    if isinstance(complaint_id, str) and complaint_id:
        complaint = get_or_404("complaints", complaint_id)
    if isinstance(officer_id, str) and officer_id:
        officer = get_or_404("officers", officer_id)

    # If FK missing entirely -> request integrity (lowest priority). But other
    # checks below need the resolved records, so only run them when present.
    # (5/6) complaint dispatchable
    if complaint is not None and complaint["status"] != "NEW":
        raise ApiError("ERR_COMPLAINT_NOT_DISPATCHABLE", 409,
                       "Complaint is not in a dispatchable state")

    sched_start = parse_dt(body.get("scheduled_start_at"))
    sched_end = parse_dt(body.get("scheduled_end_at"))

    # (8) schedule conflict — only computable with a resolved officer & windows
    if officer is not None and sched_start is not None and sched_end is not None:
        buffer = timedelta(minutes=BUFFER_MINUTES)
        for d in db["dispatches"].values():
            if d["officer_id"] != officer["id"]:
                continue
            if d["status"] not in ("PENDING", "EN_ROUTE"):
                continue
            e_start = d["scheduled_start_at"]
            e_end = d["scheduled_end_at"]
            if sched_start < e_end + buffer and sched_end > e_start - buffer:
                raise ApiError("ERR_OFFICER_SCHEDULE_CONFLICT", 409,
                               "Dispatch window conflicts with an active dispatch")

    # (9) off-duty then capacity
    if officer is not None:
        now = logical_now()
        if now < officer["shift_start_at"] or now > officer["shift_end_at"]:
            raise ApiError("ERR_OFFICER_OFF_DUTY", 409,
                           "Officer is off duty")
        if officer["active_dispatch_count"] >= officer["max_daily_dispatches"]:
            raise ApiError("ERR_OFFICER_CAPACITY_EXCEEDED", 409,
                           "Officer at dispatch capacity")

    # (12) request integrity
    if complaint is None:
        req_str(body, "complaint_id")
    if officer is None:
        req_str(body, "officer_id")
    if sched_start is None:
        req_dt(body, "scheduled_start_at")
    if sched_end is None:
        req_dt(body, "scheduled_end_at")
    eta_minutes = opt_int(body, "eta_minutes", None)
    if sched_end <= sched_start:
        invalid_request("scheduled_end_at must be after scheduled_start_at")

    rec = {
        "complaint_id": complaint["id"],
        "officer_id": officer["id"],
        "scheduled_start_at": sched_start,
        "scheduled_end_at": sched_end,
        "eta_minutes": eta_minutes,
        "field_outcome": None,
        "status": "PENDING",
    }
    stamp_new(rec)
    db["dispatches"][rec["id"]] = rec

    # side effects
    complaint["status"] = "DISPATCHED"
    touch(complaint)
    officer["active_dispatch_count"] += 1
    touch(officer)

    return resp_object(serialize(rec), 201)


@app.get("/dispatch/dispatches/<rid>")
def get_dispatch(rid):
    _, role = authenticate()
    authorize(role, {"Dispatcher", "FieldOfficer", "Supervisor"})
    rec = get_or_404("dispatches", rid)
    return resp_object(serialize(rec))


@app.get("/dispatch/dispatches")
def list_dispatches():
    _, role = authenticate()
    authorize(role, {"Dispatcher", "FieldOfficer", "Supervisor"})
    items = list(db["dispatches"].values())
    complaint_id = request.args.get("complaint_id")
    officer_id = request.args.get("officer_id")
    status = request.args.get("status")
    if complaint_id is not None:
        items = [d for d in items if d["complaint_id"] == complaint_id]
    if officer_id is not None:
        items = [d for d in items if d["officer_id"] == officer_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


@app.post("/dispatch/dispatches/<rid>/accept")
def accept_dispatch(rid):
    uid, role = authenticate()
    authorize(role, {"FieldOfficer"})
    rec = get_or_404("dispatches", rid)
    # ownership (Supervisor exempt, but only FieldOfficer allowed here)
    if role == "FieldOfficer" and uid != rec["officer_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_OFFICER", 403,
                       "Not the assigned officer")
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Dispatch is not pending")
    rec["status"] = "EN_ROUTE"
    touch(rec)
    return resp_object(serialize(rec))


@app.post("/dispatch/dispatches/<rid>/clear")
def clear_dispatch(rid):
    uid, role = authenticate()
    authorize(role, {"FieldOfficer"})
    rec = get_or_404("dispatches", rid)
    if role == "FieldOfficer" and uid != rec["officer_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_OFFICER", 403,
                       "Not the assigned officer")
    if rec["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Dispatch is not en route")
    body = get_body()
    field_outcome = req_enum(body, "field_outcome", FIELD_OUTCOMES)

    rec["status"] = "CLEARED"
    rec["field_outcome"] = field_outcome
    touch(rec)

    officer = db["officers"].get(rec["officer_id"])
    if officer is not None:
        officer["active_dispatch_count"] -= 1
        touch(officer)
    complaint = db["complaints"].get(rec["complaint_id"])
    if complaint is not None and complaint["status"] == "DISPATCHED":
        complaint["status"] = "RESOLVED"
        touch(complaint)

    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
def _severity_component(complaint):
    sev = Decimal(str(complaint["severity_score"]))
    return q2(sev * Decimal(SEV_FACTOR))


def _provisional_risk(case):
    complaint = db["complaints"].get(case["complaint_id"])
    tw = Decimal(TYPE_WEIGHT.get(case["case_type"], 0))
    comp = _severity_component(complaint) if complaint else Decimal(0)
    val = clamp(tw + comp, RISK_MIN, RISK_MAX)
    return float(q2(val))


def _final_risk(case):
    complaint = db["complaints"].get(case["complaint_id"])
    tw = Decimal(TYPE_WEIGHT.get(case["case_type"], 0))
    comp = _severity_component(complaint) if complaint else Decimal(0)
    val = clamp(tw + comp + Decimal(SUBSTANTIATION_BONUS), RISK_MIN, RISK_MAX)
    return float(q2(val))


@app.post("/dispatch/cases")
def create_case():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    body = get_body()

    complaint_id = body.get("complaint_id")
    assigned_officer_id = body.get("assigned_officer_id")
    complaint = None
    officer = None
    if isinstance(complaint_id, str) and complaint_id:
        complaint = get_or_404("complaints", complaint_id)
    if isinstance(assigned_officer_id, str) and assigned_officer_id:
        officer = get_or_404("officers", assigned_officer_id)

    if complaint is None:
        req_str(body, "complaint_id")
    if officer is None:
        req_str(body, "assigned_officer_id")
    case_type = req_enum(body, "case_type", CASE_TYPES)
    animal_identifier = body.get("animal_identifier")
    if animal_identifier is not None and not isinstance(animal_identifier, str):
        invalid_request("Invalid animal_identifier")

    rec = {
        "complaint_id": complaint["id"],
        "assigned_officer_id": officer["id"],
        "case_type": case_type,
        "animal_identifier": animal_identifier,
        "risk_score": 0,
        "outstanding_fines_total": 0,
        "public_health_flag": False,
        "substantiated_at": None,
        "status": "OPEN",
    }
    stamp_new(rec)
    db["cases"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/cases/<rid>")
def get_case(rid):
    _, role = authenticate()
    authorize(role, {"Dispatcher", "FieldOfficer", "Supervisor",
                     "HealthDeptLiaison"})
    rec = get_or_404("cases", rid)
    return resp_object(serialize(rec))


@app.get("/dispatch/cases")
def list_cases():
    _, role = authenticate()
    authorize(role, {"Dispatcher", "FieldOfficer", "Supervisor"})
    items = list(db["cases"].values())
    complaint_id = request.args.get("complaint_id")
    assigned_officer_id = request.args.get("assigned_officer_id")
    case_type = request.args.get("case_type")
    status = request.args.get("status")
    if complaint_id is not None:
        items = [c for c in items if c["complaint_id"] == complaint_id]
    if assigned_officer_id is not None:
        items = [c for c in items if c["assigned_officer_id"] == assigned_officer_id]
    if case_type is not None:
        items = [c for c in items if c["case_type"] == case_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


@app.post("/dispatch/cases/<rid>/investigate")
def investigate_case(rid):
    uid, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("cases", rid)
    # ownership
    if role == "FieldOfficer" and uid != rec["assigned_officer_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_OFFICER", 403,
                       "Not the assigned officer")
    # state: OPEN -> UNDER_INVESTIGATION (any allowed role);
    #        SUBSTANTIATED -> UNDER_INVESTIGATION (Supervisor reopen only)
    if rec["status"] == "OPEN":
        pass
    elif rec["status"] == "SUBSTANTIATED" and role == "Supervisor":
        rec["substantiated_at"] = None
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Case is not investigatable")
    rec["status"] = "UNDER_INVESTIGATION"
    rec["risk_score"] = _provisional_risk(rec)
    touch(rec)
    return resp_object(serialize(rec))


@app.post("/dispatch/cases/<rid>/resolve")
def resolve_case(rid):
    uid, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("cases", rid)
    if role == "FieldOfficer" and uid != rec["assigned_officer_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_OFFICER", 403,
                       "Not the assigned officer")
    if rec["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Case is not under investigation")
    body = get_body()
    resolution = req_enum(body, "resolution", RESOLUTIONS)

    if resolution == "SUBSTANTIATED":
        rec["status"] = "SUBSTANTIATED"
        rec["substantiated_at"] = logical_now()
        rec["risk_score"] = _final_risk(rec)
        touch(rec)
    else:  # UNFOUNDED
        rec["status"] = "UNFOUNDED"
        rec["risk_score"] = 0
        touch(rec)
        # cascade: ACTIVE quarantine holds on this case -> VOIDED
        for hold in db["quarantine_holds"].values():
            if hold["case_id"] == rec["id"] and hold["status"] == "ACTIVE":
                _void_hold(hold)

    return resp_object(serialize(rec))


@app.post("/dispatch/cases/<rid>/close")
def close_case(rid):
    _, role = authenticate()
    authorize(role, {"Supervisor"})
    rec = get_or_404("cases", rid)
    if rec["status"] not in ("SUBSTANTIATED", "UNFOUNDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Case is not resolved")
    # safety: active hold, then held impound
    for hold in db["quarantine_holds"].values():
        if hold["case_id"] == rec["id"] and hold["status"] == "ACTIVE":
            raise ApiError("ERR_ACTIVE_QUARANTINE_HOLD", 409,
                           "Case has an active quarantine hold")
    for imp in db["impounds"].values():
        if imp["case_id"] == rec["id"] and imp["status"] == "HELD":
            raise ApiError("ERR_ACTIVE_IMPOUND", 409,
                           "Case has a held impound")
    # fiscal: issued citation
    for cit in db["citations"].values():
        if cit["case_id"] == rec["id"] and cit["status"] == "ISSUED":
            raise ApiError("ERR_OUTSTANDING_CITATIONS", 409,
                           "Case has an outstanding citation")

    rec["status"] = "CLOSED"
    touch(rec)
    complaint = db["complaints"].get(rec["complaint_id"])
    if complaint is not None and complaint["status"] in ("DISPATCHED", "RESOLVED"):
        complaint["status"] = "CLOSED"
        touch(complaint)

    return resp_object(serialize(rec))


@app.post("/dispatch/cases/<rid>/notes")
def create_note(rid):
    uid, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    case = get_or_404("cases", rid)
    body = get_body()
    note_type = req_enum(body, "note_type", NOTE_TYPES)
    note_body = req_str(body, "body")

    rec = {
        "case_id": case["id"],
        "note_type": note_type,
        "body": note_body,
        "author_role": role,
        "author_id": uid,
    }
    stamp_new(rec, common=False)
    db["notes"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/cases/<rid>/notes")
def list_notes(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor", "HealthDeptLiaison"})
    case = get_or_404("cases", rid)
    items = [n for n in db["notes"].values() if n["case_id"] == case["id"]]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# QuarantineHold
# ---------------------------------------------------------------------------
@app.post("/dispatch/quarantine-holds")
def create_quarantine_hold():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    body = get_body()

    case_id = body.get("case_id")
    case = None
    if isinstance(case_id, str) and case_id:
        case = get_or_404("cases", case_id)

    if case is not None:
        # (6) eligibility: type first, then actionable status
        if case["case_type"] not in ("BITE", "DANGEROUS_DOG"):
            raise ApiError("ERR_CASE_TYPE_NOT_ELIGIBLE", 409,
                           "Case type not eligible for quarantine")
        if case["status"] not in ("UNDER_INVESTIGATION", "SUBSTANTIATED"):
            raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409,
                           "Case not actionable")

    if case is None:
        req_str(body, "case_id")
    hold_type = req_enum(body, "hold_type", HOLD_TYPES)
    start_at = req_dt(body, "start_at")
    animal_identifier = body.get("animal_identifier")
    if animal_identifier is not None and not isinstance(animal_identifier, str):
        invalid_request("Invalid animal_identifier")

    if case["case_type"] == "DANGEROUS_DOG":
        required_days = DANGEROUS_DOG_DAYS
    else:  # BITE or any other eligible input
        required_days = BITE_DAYS
    release_due = start_at + timedelta(days=required_days)

    rec = {
        "case_id": case["id"],
        "animal_identifier": animal_identifier,
        "hold_type": hold_type,
        "start_at": start_at,
        "required_days": required_days,
        "release_due_at": release_due,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db["quarantine_holds"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/quarantine-holds/<rid>")
def get_quarantine_hold(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor", "HealthDeptLiaison"})
    rec = get_or_404("quarantine_holds", rid)
    return resp_object(serialize(rec))


@app.get("/dispatch/quarantine-holds")
def list_quarantine_holds():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor", "HealthDeptLiaison"})
    items = list(db["quarantine_holds"].values())
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [h for h in items if h["case_id"] == case_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


@app.post("/dispatch/quarantine-holds/<rid>/release")
def release_quarantine_hold(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("quarantine_holds", rid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Hold is not active")
    if logical_now() < rec["release_due_at"]:
        raise ApiError("ERR_QUARANTINE_NOT_ELAPSED", 409,
                       "Observation window has not elapsed")
    rec["status"] = "RELEASED"
    touch(rec)
    return resp_object(serialize(rec))


@app.post("/dispatch/quarantine-holds/<rid>/escalate")
def escalate_quarantine_hold(rid):
    _, role = authenticate()
    authorize(role, {"Supervisor"})
    rec = get_or_404("quarantine_holds", rid)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Hold is not active")
    rec["status"] = "ESCALATED"
    touch(rec)
    # cascade hop 1: HELD impounds on the same case -> EUTHANIZED (system)
    for imp in list(db["impounds"].values()):
        if imp["case_id"] == rec["case_id"] and imp["status"] == "HELD":
            _cascade_euthanize_impound(imp)
    return resp_object(serialize(rec))


def _void_hold(hold):
    """Cascade: Case UNFOUNDED -> ACTIVE hold VOIDED -> SUBMITTED reports CLEARED."""
    hold["status"] = "VOIDED"
    touch(hold)
    for rep in db["rabies_reports"].values():
        if rep["quarantine_hold_id"] == hold["id"] and rep["status"] == "SUBMITTED":
            rep["status"] = "CLEARED"
            touch(rep)


def _cascade_euthanize_impound(imp):
    """System euthanasia via quarantine escalation (no boarding fee)."""
    imp["status"] = "EUTHANIZED"
    touch(imp)
    kennel = db["kennels"].get(imp["kennel_id"])
    if kennel is not None:
        kennel["occupied_slots"] -= 1
        touch(kennel)
    # cascade hop 2: SUBMITTED rabies reports on same case -> ESCALATED
    for rep in db["rabies_reports"].values():
        if rep["case_id"] == imp["case_id"] and rep["status"] == "SUBMITTED":
            _escalate_report(rep)


def _escalate_report(rep):
    """Cascade hop 3: flag case for public health, +20 risk clamped."""
    rep["status"] = "ESCALATED"
    touch(rep)
    case = db["cases"].get(rep["case_id"])
    if case is not None:
        case["public_health_flag"] = True
        new_risk = clamp(Decimal(str(case["risk_score"])) + Decimal(20),
                         RISK_MIN, RISK_MAX)
        case["risk_score"] = float(q2(new_risk))
        touch(case)


# ---------------------------------------------------------------------------
# Impound
# ---------------------------------------------------------------------------
@app.post("/dispatch/impounds")
def create_impound():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    body = get_body()

    # existence (left-to-right): case then kennel
    case_id = body.get("case_id")
    kennel_id = body.get("kennel_id")
    case = None
    kennel = None
    if isinstance(case_id, str) and case_id:
        case = get_or_404("cases", case_id)
    if isinstance(kennel_id, str) and kennel_id:
        kennel = get_or_404("kennels", kennel_id)

    # (6) eligibility: case actionable status
    if case is not None and case["status"] not in ("UNDER_INVESTIGATION",
                                                    "SUBSTANTIATED"):
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409, "Case not actionable")

    impounded_at = parse_dt(body.get("impounded_at"))
    hold_until = parse_dt(body.get("hold_until"))

    # (8) kennel overlap — closed intervals, touching allowed
    if kennel is not None and impounded_at is not None and hold_until is not None:
        for imp in db["impounds"].values():
            if imp["kennel_id"] != kennel["id"] or imp["status"] != "HELD":
                continue
            if impounded_at < imp["hold_until"] and hold_until > imp["impounded_at"]:
                raise ApiError("ERR_KENNEL_OCCUPIED", 409,
                               "Kennel occupancy window overlaps a held impound")

    # (11) OCC on Case.version
    expected = body.get("expected_case_version")
    if case is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != case["version"]:
            raise ApiError("ERR_STALE_CASE_VERSION", 412,
                           "expected_case_version does not match current case version")

    # (12) request integrity
    if case is None:
        req_str(body, "case_id")
    if kennel is None:
        req_str(body, "kennel_id")
    if impounded_at is None:
        req_dt(body, "impounded_at")
    if hold_until is None:
        req_dt(body, "hold_until")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        invalid_request("Missing or invalid expected_case_version")
    licensed = opt_bool(body, "licensed", False)
    animal_identifier = body.get("animal_identifier")
    if animal_identifier is not None and not isinstance(animal_identifier, str):
        invalid_request("Invalid animal_identifier")
    if hold_until <= impounded_at:
        invalid_request("hold_until must be after impounded_at")

    rec = {
        "case_id": case["id"],
        "kennel_id": kennel["id"],
        "animal_identifier": animal_identifier,
        "licensed": licensed,
        "impounded_at": impounded_at,
        "hold_until": hold_until,
        "boarding_fee": 0,
        "status": "HELD",
    }
    stamp_new(rec)
    db["impounds"][rec["id"]] = rec

    kennel["occupied_slots"] += 1
    touch(kennel)
    case["version"] += 1
    case["updated_at"] = real_now()

    return resp_object(serialize(rec), 201)


@app.get("/dispatch/impounds/<rid>")
def get_impound(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("impounds", rid)
    return resp_object(serialize(rec))


@app.get("/dispatch/impounds")
def list_impounds():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    items = list(db["impounds"].values())
    case_id = request.args.get("case_id")
    kennel_id = request.args.get("kennel_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [i for i in items if i["case_id"] == case_id]
    if kennel_id is not None:
        items = [i for i in items if i["kennel_id"] == kennel_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


def _compute_boarding_fee(imp):
    released_at = logical_now()
    elapsed = (released_at - imp["impounded_at"]).total_seconds()
    days = max(1, math.ceil(elapsed / SECONDS_PER_DAY))
    tax = Decimal(TAX_RATE)
    daily_charge = Decimal(days) * Decimal(DAILY_RATE)
    intake = Decimal(INTAKE_FEE)
    surcharge = Decimal("0") if imp["licensed"] else Decimal(UNLICENSED_SURCHARGE)
    fee = q2(daily_charge * tax) + q2(intake * tax) + q2(surcharge * tax)
    return float(q2(fee))


@app.post("/dispatch/impounds/<rid>/release")
def release_impound(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("impounds", rid)
    if rec["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Impound is not held")
    body = get_body()
    disposition = req_enum(body, "disposition", DISPOSITIONS)

    rec["status"] = disposition
    rec["boarding_fee"] = _compute_boarding_fee(rec)
    touch(rec)
    kennel = db["kennels"].get(rec["kennel_id"])
    if kennel is not None:
        kennel["occupied_slots"] -= 1
        touch(kennel)
    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------
@app.post("/dispatch/citations")
def create_citation():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    body = get_body()

    case_id = body.get("case_id")
    case = None
    if isinstance(case_id, str) and case_id:
        case = get_or_404("cases", case_id)

    if case is not None and case["status"] not in ("UNDER_INVESTIGATION",
                                                   "SUBSTANTIATED"):
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409, "Case not actionable")

    if case is None:
        req_str(body, "case_id")
    violation_code = req_enum(body, "violation_code", VIOLATION_CODES)
    issued_to_name = req_str(body, "issued_to_name")
    issued_to_ref = req_str(body, "issued_to_ref")

    base_fine = VIOLATION_FINE[violation_code]
    prior = sum(
        1 for c in db["citations"].values()
        if c["issued_to_ref"] == issued_to_ref
        and c["status"] in ("PAID", "COURT_REFERRED")
    )
    if prior >= 1:
        mult = Decimal(1) + Decimal(min(prior, 3)) * Decimal("0.5")
    else:
        mult = Decimal(1)
    fine_amount = float(q2(Decimal(base_fine) * mult))

    issued_at = logical_now()
    due_at = issued_at + timedelta(days=30)

    rec = {
        "case_id": case["id"],
        "violation_code": violation_code,
        "issued_to_name": issued_to_name,
        "issued_to_ref": issued_to_ref,
        "base_fine": base_fine,
        "fine_amount": fine_amount,
        "issued_at": issued_at,
        "due_at": due_at,
        "status": "ISSUED",
    }
    stamp_new(rec)
    db["citations"][rec["id"]] = rec

    _adjust_outstanding(case, fine_amount)

    return resp_object(serialize(rec), 201)


def _adjust_outstanding(case, delta):
    current = Decimal(str(case["outstanding_fines_total"]))
    case["outstanding_fines_total"] = float(q2(current + Decimal(str(delta))))
    touch(case)


@app.get("/dispatch/citations/<rid>")
def get_citation(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    rec = get_or_404("citations", rid)
    return resp_object(serialize(rec))


@app.get("/dispatch/citations")
def list_citations():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    items = list(db["citations"].values())
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


@app.post("/dispatch/citations/<rid>/pay")
def pay_citation(rid):
    _, role = authenticate()
    authorize(role, {"Dispatcher", "Supervisor"})
    rec = get_or_404("citations", rid)
    if rec["status"] != "ISSUED":
        raise ApiError("ERR_CITATION_ALREADY_RESOLVED", 409,
                       "Citation already resolved")
    rec["status"] = "PAID"
    touch(rec)
    case = db["cases"].get(rec["case_id"])
    if case is not None:
        _adjust_outstanding(case, -rec["fine_amount"])
    return resp_object(serialize(rec))


@app.post("/dispatch/citations/<rid>/refer-court")
def refer_citation(rid):
    _, role = authenticate()
    authorize(role, {"Supervisor"})
    rec = get_or_404("citations", rid)
    if rec["status"] != "ISSUED":
        raise ApiError("ERR_CITATION_ALREADY_RESOLVED", 409,
                       "Citation already resolved")
    rec["status"] = "COURT_REFERRED"
    touch(rec)
    case = db["cases"].get(rec["case_id"])
    if case is not None:
        _adjust_outstanding(case, -rec["fine_amount"])
    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# RabiesReport
# ---------------------------------------------------------------------------
@app.post("/dispatch/rabies-reports")
def create_rabies_report():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor"})
    body = get_body()

    # existence (left-to-right): case then quarantine hold
    case_id = body.get("case_id")
    hold_id = body.get("quarantine_hold_id")
    case = None
    hold = None
    if isinstance(case_id, str) and case_id:
        case = get_or_404("cases", case_id)
    if isinstance(hold_id, str) and hold_id:
        hold = get_or_404("quarantine_holds", hold_id)

    # (6) eligibility: case type must be BITE or DANGEROUS_DOG
    if case is not None and case["case_type"] not in ("BITE", "DANGEROUS_DOG"):
        raise ApiError("ERR_CASE_TYPE_NOT_ELIGIBLE", 409,
                       "Case type not eligible for rabies report")

    if case is None:
        req_str(body, "case_id")
    if hold is None:
        req_str(body, "quarantine_hold_id")
    victim_name = req_str(body, "victim_name")
    exposure_date = req_dt(body, "exposure_date")
    animal_identifier = body.get("animal_identifier")
    if animal_identifier is not None and not isinstance(animal_identifier, str):
        invalid_request("Invalid animal_identifier")

    submitted_at = logical_now()
    deadline_at = exposure_date + timedelta(hours=24)
    is_late = submitted_at > deadline_at

    rec = {
        "case_id": case["id"],
        "quarantine_hold_id": hold["id"],
        "animal_identifier": animal_identifier,
        "victim_name": victim_name,
        "exposure_date": exposure_date,
        "deadline_at": deadline_at,
        "submitted_at": submitted_at,
        "is_late": is_late,
        "status": "SUBMITTED",
    }
    stamp_new(rec)
    db["rabies_reports"][rec["id"]] = rec
    return resp_object(serialize(rec), 201)


@app.get("/dispatch/rabies-reports/<rid>")
def get_rabies_report(rid):
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor", "HealthDeptLiaison"})
    rec = get_or_404("rabies_reports", rid)
    return resp_object(serialize(rec))


@app.get("/dispatch/rabies-reports")
def list_rabies_reports():
    _, role = authenticate()
    authorize(role, {"FieldOfficer", "Supervisor", "HealthDeptLiaison"})
    items = list(db["rabies_reports"].values())
    case_id = request.args.get("case_id")
    hold_id = request.args.get("quarantine_hold_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [r for r in items if r["case_id"] == case_id]
    if hold_id is not None:
        items = [r for r in items if r["quarantine_hold_id"] == hold_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_seq(items)
    page, limit, offset, total = paginate(items)
    return resp_array([serialize(r) for r in page], limit, offset, total)


@app.post("/dispatch/rabies-reports/<rid>/clear")
def clear_rabies_report(rid):
    _, role = authenticate()
    authorize(role, {"HealthDeptLiaison"})
    rec = get_or_404("rabies_reports", rid)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not submitted")
    rec["status"] = "CLEARED"
    touch(rec)
    return resp_object(serialize(rec))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
@app.get("/dispatch/reports/summary")
def reports_summary():
    _, role = authenticate()
    authorize(role, {"Dispatcher", "Supervisor"})
    total_complaints = len(db["complaints"])
    open_cases = sum(1 for c in db["cases"].values()
                     if c["status"] in ("OPEN", "UNDER_INVESTIGATION"))
    active_holds = sum(1 for h in db["quarantine_holds"].values()
                       if h["status"] == "ACTIVE")
    total = Decimal(0)
    for cit in db["citations"].values():
        if cit["status"] == "ISSUED":
            total += Decimal(str(cit["fine_amount"]))
    data = {
        "total_complaints": total_complaints,
        "open_cases": open_cases,
        "active_quarantine_holds": active_holds,
        "total_outstanding_fines": float(q2(total)),
    }
    return resp_object(data)


# ---------------------------------------------------------------------------
# Logical clock control
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    authorize(role, {"Supervisor"})
    body = get_body()
    target = req_dt(body, "to_iso8601")
    CLOCK["now"] = target
    return resp_object({"current_utc": fmt_dt(target)})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
