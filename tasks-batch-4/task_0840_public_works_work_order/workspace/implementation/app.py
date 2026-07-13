"""
Public Works Work-Order & Asset Management API.

Single-file Flask implementation. All state is in-memory (Python dicts keyed by
id) and starts EMPTY on every boot — no seeding, no persistence. The test harness
re-launches this process before every test via start.sh, which wipes all state.
"""

import os
import re
import uuid
import random
import string
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (empty on boot)
# ---------------------------------------------------------------------------
DB = {
    "assets": {},
    "inspections": {},
    "service_requests": {},
    "work_orders": {},
    "crews": {},
    "dispatches": {},
    "yards": {},
    "material_items": {},
    "material_reservations": {},
    "row_permits": {},
}

# Logical clock — server startup default per PRD §2.7
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


ROLES = {"Supervisor", "Inspector", "Dispatcher", "CrewLead", "Coordinator"}
ALL_ROLES = ["Supervisor", "Dispatcher", "Inspector", "CrewLead", "Coordinator"]

# Terminal states per entity (PRD §2.10)
TERMINAL = {
    "assets": {"RETIRED"},
    "inspections": {"ACCEPTED"},
    "service_requests": {"CLOSED", "DUPLICATE"},
    "work_orders": {"COMPLETED", "CANCELLED"},
    "dispatches": {"RELEASED", "CANCELLED"},
    "material_reservations": {"CONSUMED", "RELEASED"},
    "row_permits": {"DENIED", "RELEASED"},
}

NON_TERMINAL_WO = {"DRAFT", "SCHEDULED", "DISPATCHED", "IN_PROGRESS", "ON_HOLD"}

NOT_FOUND_ERR = {
    "assets": "ERR_ASSET_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "service_requests": "ERR_SERVICE_REQUEST_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "crews": "ERR_CREW_NOT_FOUND",
    "material_items": "ERR_MATERIAL_ITEM_NOT_FOUND",
    "material_reservations": "ERR_MATERIAL_RESERVATION_NOT_FOUND",
    "row_permits": "ERR_ROW_PERMIT_NOT_FOUND",
    "dispatches": "ERR_DISPATCH_NOT_FOUND",
    "yards": "ERR_YARD_NOT_FOUND",
}

# Datetime-typed fields per collection (serialized as ISO strings)
DATETIME_FIELDS = {
    "assets": {"install_date", "last_inspection_at", "created_at", "updated_at"},
    "inspections": {"scheduled_window_start", "scheduled_window_end", "created_at", "updated_at"},
    "service_requests": {"sla_due_at", "created_at", "updated_at"},
    "work_orders": {"scheduled_start", "scheduled_end", "created_at", "updated_at"},
    "crews": {"created_at", "updated_at"},
    "dispatches": {"window_start", "window_end", "created_at", "updated_at"},
    "yards": {"created_at", "updated_at"},
    "material_items": {"created_at", "updated_at"},
    "material_reservations": {"created_at", "updated_at"},
    "row_permits": {"window_start", "window_end", "created_at", "updated_at"},
}

# Calculation constants
AGE_PENALTY_PER_YEAR = Decimal("1.5")
MAX_AGE_PENALTY = Decimal("25")
PREVENTIVE_AGE_FACTOR = Decimal("0.5")
SEVERITY_WEIGHT = {"ROAD": Decimal("1.0"), "SIGN": Decimal("0.6"), "SIGNAL": Decimal("0.8")}
OT_THRESHOLD_HOURS = Decimal("8")
OT_MULTIPLIER = Decimal("1.5")
CAPITALIZATION_THRESHOLD_CENTS = 500000
BETTERMENT_PCT = Decimal("0.25")
MOBILIZATION_BUFFER = timedelta(minutes=30)

CATEGORY_PRIORITY = {"SIGNAL_OUTAGE": "EMERGENCY", "POTHOLE": "HIGH", "SIGN_DAMAGE": "MEDIUM"}
SLA_HOURS = {"EMERGENCY": 4, "HIGH": 48, "MEDIUM": 120, "LOW": 240}

# Enum domains
ENUMS = {
    "asset_class": {"ROAD", "SIGN", "SIGNAL"},
    "inspection_type": {"PREVENTIVE", "CONDITION"},
    "channel": {"PHONE", "WEB", "APP"},
    "category": {"POTHOLE", "SIGN_DAMAGE", "SIGNAL_OUTAGE"},
    "work_type": {"MAINTENANCE", "CAPITAL"},
    "origin": {"INSPECTION", "SERVICE_REQUEST", "PREVENTIVE"},
    "priority": {"LOW", "MEDIUM", "HIGH", "EMERGENCY"},
    "crew_type": {"PAVING", "SIGNS", "SIGNALS"},
    "material_type": {"ASPHALT_TON", "SIGN_BLANK", "SIGNAL_LAMP"},
    "permit_type": {"LANE_CLOSURE", "EXCAVATION", "UTILITY_COORD"},
}


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
def now():
    return CLOCK["now"]


def parse_iso(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s == "":
        raise ValueError("empty")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(x):
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def request_meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": format_iso(datetime.now(timezone.utc))}


def serialize(collection, record):
    dt_fields = DATETIME_FIELDS.get(collection, set())
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if k in dt_fields:
            out[k] = format_iso(v) if v is not None else None
        else:
            out[k] = v
    if collection == "material_items":
        out["available_qty"] = record["on_hand_qty"] - record["reserved_qty"]
    return out


def ok(collection, record, code=200):
    meta = request_meta()
    body = {"meta": meta, "response_type": "object",
            "data": serialize(collection, record) if record is not None else {}}
    return jsonify(body), code


def ok_empty(code=200):
    return jsonify({"meta": request_meta(), "response_type": "object", "data": {}}), code


def ok_list(collection, records, limit, offset, total):
    meta = request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(records)) < total
    body = {"meta": meta, "response_type": "array",
            "data": [serialize(collection, r) for r in records]}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"meta": request_meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {"meta": request_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {"meta": request_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return user_id, role


def require(allowed_roles):
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return user_id, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return body


def validation_error(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, field):
    if field not in body or body[field] is None:
        validation_error("Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        validation_error("Field %s must be a non-empty string" % field)
    return v


def req_enum(body, field):
    v = req_str(body, field)
    if v not in ENUMS[field]:
        validation_error("Illegal value for %s: %s" % (field, v))
    return v


def opt_enum(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in ENUMS[field]:
        validation_error("Illegal value for %s: %s" % (field, v))
    return v


def req_number(body, field, *, minimum=None, maximum=None, exclusive_min=None):
    if field not in body or body[field] is None:
        validation_error("Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        validation_error("Field %s must be a number" % field)
    if minimum is not None and v < minimum:
        validation_error("Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        validation_error("Field %s must be <= %s" % (field, maximum))
    if exclusive_min is not None and v <= exclusive_min:
        validation_error("Field %s must be > %s" % (field, exclusive_min))
    return v


def req_int(body, field, *, minimum=None):
    if field not in body or body[field] is None:
        validation_error("Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        validation_error("Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        validation_error("Field %s must be >= %s" % (field, minimum))
    return v


def opt_int(body, field, default, *, minimum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum=minimum)


def req_datetime(body, field):
    if field not in body or body[field] is None:
        validation_error("Missing required field: %s" % field)
    try:
        return parse_iso(body[field])
    except Exception:
        validation_error("Field %s must be a valid ISO-8601 datetime" % field)


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        validation_error("Field %s must be a boolean" % field)
    return v


def lookup(collection, rid):
    rec = DB[collection].get(rid)
    if rec is None:
        raise ApiError(NOT_FOUND_ERR[collection], 404, "%s not found" % collection)
    return rec


def check_not_terminal(collection, rec):
    if rec["status"] in TERMINAL.get(collection, set()):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Resource is in a terminal state")


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(extra):
    ts = now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def paginate_and_filter(collection, filters):
    # pagination
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            validation_error("limit must be an integer")
        if limit < 1 or limit > 100:
            validation_error("limit out of bounds")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            validation_error("offset must be an integer")
        if offset < 0:
            validation_error("offset out of bounds")

    records = list(DB[collection].values())
    for key in filters:
        val = args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    records.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Computed helpers
# ---------------------------------------------------------------------------
def compute_pci(asset, inspection_type, raw_distress_index):
    sw = SEVERITY_WEIGHT[asset["asset_class"]]
    days = (now() - asset["install_date"]).total_seconds() / 86400.0
    age_years = int(math.floor(days / 365.25))
    if age_years < 0:
        age_years = 0
    penalty = to_decimal(age_years) * AGE_PENALTY_PER_YEAR
    if inspection_type == "PREVENTIVE":
        penalty = penalty * PREVENTIVE_AGE_FACTOR
    if penalty > MAX_AGE_PENALTY:
        penalty = MAX_AGE_PENALTY
    base = to_decimal(100) - to_decimal(raw_distress_index) * sw
    pci = round_half_up(base - penalty)
    if pci < 0:
        pci = 0
    if pci > 100:
        pci = 100
    return pci


def condition_state_for(pci):
    if pci >= 85:
        return "GOOD"
    if pci >= 70:
        return "FAIR"
    if pci >= 55:
        return "POOR"
    return "FAILED"


def compute_labor_cost(labor_hours, hourly_rate_cents):
    lh = to_decimal(labor_hours)
    rate = to_decimal(hourly_rate_cents)
    regular = min(lh, OT_THRESHOLD_HOURS)
    overtime = lh - OT_THRESHOLD_HOURS
    if overtime < 0:
        overtime = Decimal(0)
    total = regular * rate + overtime * rate * OT_MULTIPLIER
    return round_half_up(total)


def window_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def crew_has_active_dispatch(crew_id, exclude_id=None):
    for d in DB["dispatches"].values():
        if d["crew_id"] == crew_id and d["id"] != exclude_id and d["status"] in ("RESERVED", "ACTIVE"):
            return True
    return False


def asset_has_non_terminal_wo(asset_id, exclude_id=None):
    for wo in DB["work_orders"].values():
        if wo["asset_id"] == asset_id and wo["id"] != exclude_id and wo["status"] in NON_TERMINAL_WO:
            return True
    return False


def release_dispatch(d):
    """Release an ACTIVE/RESERVED dispatch on WO completion."""
    d["status"] = "RELEASED"
    touch(d)
    crew = DB["crews"].get(d["crew_id"])
    if crew is not None:
        crew["committed_minutes"] -= window_minutes(d["window_start"], d["window_end"])
        if not crew_has_active_dispatch(crew["id"]):
            crew["status"] = "AVAILABLE"
        touch(crew)


def cancel_dispatch_internal(d):
    d["status"] = "CANCELLED"
    touch(d)
    crew = DB["crews"].get(d["crew_id"])
    if crew is not None:
        crew["committed_minutes"] -= window_minutes(d["window_start"], d["window_end"])
        if not crew_has_active_dispatch(crew["id"]):
            crew["status"] = "AVAILABLE"
        touch(crew)


# ===========================================================================
# ASSET endpoints
# ===========================================================================
@app.route("/assets", methods=["POST"])
def create_asset():
    require(["Supervisor"])
    body = get_body()
    asset_class = req_enum(body, "asset_class")
    gis_segment_id = req_str(body, "gis_segment_id")
    location_desc = req_str(body, "location_desc")
    install_date = req_datetime(body, "install_date")
    replacement_value_cents = req_int(body, "replacement_value_cents", minimum=0)
    rec = new_record({
        "asset_class": asset_class,
        "gis_segment_id": gis_segment_id,
        "location_desc": location_desc,
        "install_date": install_date,
        "replacement_value_cents": replacement_value_cents,
        "status": "ACTIVE",
        "pci_score": None,
        "condition_state": None,
        "last_inspection_at": None,
        "maintenance_cost_to_date_cents": 0,
        "capital_cost_to_date_cents": 0,
    })
    DB["assets"][rec["id"]] = rec
    return ok("assets", rec, 201)


@app.route("/assets/<rid>", methods=["GET"])
def get_asset(rid):
    require(ALL_ROLES)
    return ok("assets", lookup("assets", rid))


@app.route("/assets", methods=["GET"])
def list_assets():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "assets", ["asset_class", "status", "condition_state"])
    return ok_list("assets", page, limit, offset, total)


@app.route("/assets/<rid>/retire", methods=["POST"])
def retire_asset(rid):
    require(["Supervisor"])
    get_body()
    asset = lookup("assets", rid)
    check_not_terminal("assets", asset)
    if asset["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Asset is not ACTIVE")
    if asset_has_non_terminal_wo(asset["id"]):
        raise ApiError("ERR_ASSET_HAS_OPEN_WORKORDER", 409, "Asset has an open work order")
    asset["status"] = "RETIRED"
    touch(asset)
    return ok("assets", asset)


# ===========================================================================
# INSPECTION endpoints
# ===========================================================================
@app.route("/inspections", methods=["POST"])
def create_inspection():
    user_id, _ = require(["Inspector"])
    body = get_body()
    inspection_type = req_enum(body, "inspection_type")
    raw_distress_index = req_number(body, "raw_distress_index", minimum=0, maximum=100)
    scheduled_window_start = req_datetime(body, "scheduled_window_start")
    scheduled_window_end = req_datetime(body, "scheduled_window_end")
    # existence (asset_id)
    if "asset_id" not in body or body["asset_id"] is None:
        validation_error("Missing required field: asset_id")
    asset = lookup("assets", body["asset_id"])
    computed_pci = compute_pci(asset, inspection_type, raw_distress_index)
    rec = new_record({
        "asset_id": asset["id"],
        "inspector_id": user_id,
        "inspection_type": inspection_type,
        "raw_distress_index": raw_distress_index,
        "computed_pci": computed_pci,
        "scheduled_window_start": scheduled_window_start,
        "scheduled_window_end": scheduled_window_end,
        "status": "DRAFT",
        "decided_by": None,
    })
    DB["inspections"][rec["id"]] = rec
    return ok("inspections", rec, 201)


@app.route("/inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    require(ALL_ROLES)
    return ok("inspections", lookup("inspections", rid))


@app.route("/inspections", methods=["GET"])
def list_inspections():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter("inspections", ["asset_id", "status"])
    return ok_list("inspections", page, limit, offset, total)


@app.route("/inspections/<rid>/submit", methods=["POST"])
def submit_inspection(rid):
    require(["Inspector"])
    get_body()
    insp = lookup("inspections", rid)
    check_not_terminal("inspections", insp)
    if insp["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection cannot be submitted from its current state")
    insp["status"] = "SUBMITTED"
    touch(insp)
    return ok("inspections", insp)


@app.route("/inspections/<rid>/decision", methods=["POST"])
def decide_inspection(rid):
    user_id, _ = require(["Supervisor"])
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("ACCEPT", "REJECT"):
        validation_error("decision must be ACCEPT or REJECT")
    insp = lookup("inspections", rid)
    check_not_terminal("inspections", insp)
    if insp["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is not SUBMITTED")
    asset = DB["assets"].get(insp["asset_id"])

    if decision == "REJECT":
        insp["decided_by"] = user_id
        insp["status"] = "REJECTED"
        touch(insp)
        return ok("inspections", insp)

    # ACCEPT
    if asset is not None and asset["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "Cannot accept inspection for a retired asset")
    if user_id == insp["inspector_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Decider cannot be the inspection author")

    insp["decided_by"] = user_id
    insp["status"] = "ACCEPTED"
    touch(insp)

    # Asset cascade (one asset version bump for the whole acceptance)
    asset["pci_score"] = insp["computed_pci"]
    asset["condition_state"] = condition_state_for(insp["computed_pci"])
    asset["last_inspection_at"] = now()
    if asset["condition_state"] == "FAILED" and asset["status"] == "ACTIVE":
        wo = new_record({
            "asset_id": asset["id"],
            "service_request_id": None,
            "work_type": "MAINTENANCE",
            "origin": "INSPECTION",
            "priority": "MEDIUM",
            "scheduled_start": None,
            "scheduled_end": None,
            "estimated_cost_cents": 0,
            "labor_cost_cents": 0,
            "material_cost_cents": 0,
            "actual_cost_cents": 0,
            "capitalized": False,
            "status": "DRAFT",
        })
        DB["work_orders"][wo["id"]] = wo
        asset["status"] = "UNDER_REPAIR"
    touch(asset)
    return ok("inspections", insp)


# ===========================================================================
# SERVICE REQUEST endpoints
# ===========================================================================
@app.route("/service-requests", methods=["POST"])
def create_service_request():
    require(["Dispatcher"])
    body = get_body()
    channel = req_enum(body, "channel")
    category = req_enum(body, "category")
    reported_by = req_str(body, "reported_by")
    location_desc = req_str(body, "location_desc")
    if "asset_id" not in body or body["asset_id"] is None:
        validation_error("Missing required field: asset_id")
    asset = lookup("assets", body["asset_id"])
    priority = CATEGORY_PRIORITY[category]
    created = now()
    sla_due_at = created + timedelta(hours=SLA_HOURS[priority])
    rec = new_record({
        "asset_id": asset["id"],
        "channel": channel,
        "category": category,
        "reported_by": reported_by,
        "location_desc": location_desc,
        "priority": priority,
        "sla_due_at": sla_due_at,
        "duplicate_of_id": None,
        "status": "NEW",
    })
    DB["service_requests"][rec["id"]] = rec
    return ok("service_requests", rec, 201)


@app.route("/service-requests/<rid>", methods=["GET"])
def get_service_request(rid):
    require(ALL_ROLES)
    return ok("service_requests", lookup("service_requests", rid))


@app.route("/service-requests", methods=["GET"])
def list_service_requests():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "service_requests", ["asset_id", "status", "duplicate_of_id"])
    return ok_list("service_requests", page, limit, offset, total)


@app.route("/service-requests/<rid>/triage", methods=["POST"])
def triage_service_request(rid):
    require(["Dispatcher"])
    body = get_body()
    dup_id = body.get("duplicate_of_id")
    if dup_id is not None and not isinstance(dup_id, str):
        validation_error("duplicate_of_id must be a string")
    sr = lookup("service_requests", rid)
    # existence of duplicate_of_id FK (priority 4) before state
    if dup_id is not None:
        lookup("service_requests", dup_id)
    check_not_terminal("service_requests", sr)
    if sr["status"] != "NEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Service request is not NEW")
    if dup_id is not None:
        if dup_id == sr["id"]:
            raise ApiError("ERR_DUPLICATE_SELF", 409, "Cannot mark a request as a duplicate of itself")
        sr["duplicate_of_id"] = dup_id
        sr["status"] = "DUPLICATE"
    else:
        sr["status"] = "TRIAGED"
    touch(sr)
    return ok("service_requests", sr)


# ===========================================================================
# WORK ORDER endpoints
# ===========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    require(["Dispatcher"])
    body = get_body()
    work_type = req_enum(body, "work_type")
    origin = req_enum(body, "origin")
    priority = opt_enum(body, "priority", "MEDIUM")
    estimated_cost_cents = opt_int(body, "estimated_cost_cents", 0, minimum=0)
    if "asset_id" not in body or body["asset_id"] is None:
        validation_error("Missing required field: asset_id")
    asset = lookup("assets", body["asset_id"])
    sr = None
    service_request_id = body.get("service_request_id")
    if service_request_id is not None:
        sr = lookup("service_requests", service_request_id)
    rec = new_record({
        "asset_id": asset["id"],
        "service_request_id": service_request_id,
        "work_type": work_type,
        "origin": origin,
        "priority": priority,
        "scheduled_start": None,
        "scheduled_end": None,
        "estimated_cost_cents": estimated_cost_cents,
        "labor_cost_cents": 0,
        "material_cost_cents": 0,
        "actual_cost_cents": 0,
        "capitalized": False,
        "status": "DRAFT",
    })
    DB["work_orders"][rec["id"]] = rec
    if sr is not None and sr["status"] == "TRIAGED":
        sr["status"] = "LINKED"
        touch(sr)
    return ok("work_orders", rec, 201)


@app.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    require(ALL_ROLES)
    return ok("work_orders", lookup("work_orders", rid))


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "work_orders", ["asset_id", "service_request_id", "status", "work_type"])
    return ok_list("work_orders", page, limit, offset, total)


@app.route("/work-orders/<rid>/schedule", methods=["POST"])
def schedule_work_order(rid):
    require(["Dispatcher"])
    body = get_body()
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        validation_error("scheduled_end must be after scheduled_start")
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not DRAFT")
    wo["scheduled_start"] = scheduled_start
    wo["scheduled_end"] = scheduled_end
    wo["status"] = "SCHEDULED"
    touch(wo)
    return ok("work_orders", wo)


@app.route("/work-orders/<rid>/dispatch", methods=["POST"])
def dispatch_work_order(rid):
    require(["Dispatcher"])
    get_body()
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not SCHEDULED")
    permits = [p for p in DB["row_permits"].values() if p["work_order_id"] == wo["id"]]
    for p in permits:
        if p["clearance_required"] and p["status"] != "APPROVED":
            raise ApiError("ERR_ROW_NOT_APPROVED", 409, "A clearance-required permit is not APPROVED")
    reserved = [d for d in DB["dispatches"].values()
                if d["work_order_id"] == wo["id"] and d["status"] == "RESERVED"]
    if not reserved:
        raise ApiError("ERR_NO_DISPATCH_FOR_WORKORDER", 409, "No reserved dispatch for this work order")
    for d in reserved:
        d["status"] = "ACTIVE"
        touch(d)
    for p in permits:
        if p["status"] == "APPROVED":
            p["status"] = "ACTIVE"
            touch(p)
    wo["status"] = "DISPATCHED"
    touch(wo)
    return ok("work_orders", wo)


@app.route("/work-orders/<rid>/start", methods=["POST"])
def start_work_order(rid):
    require(["CrewLead"])
    get_body()
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not DISPATCHED")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return ok("work_orders", wo)


@app.route("/work-orders/<rid>/hold", methods=["POST"])
def hold_work_order(rid):
    require(["CrewLead"])
    get_body()
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not IN_PROGRESS")
    wo["status"] = "ON_HOLD"
    touch(wo)
    return ok("work_orders", wo)


@app.route("/work-orders/<rid>/resume", methods=["POST"])
def resume_work_order(rid):
    require(["CrewLead"])
    get_body()
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not ON_HOLD")
    wo["status"] = "IN_PROGRESS"
    touch(wo)
    return ok("work_orders", wo)


@app.route("/work-orders/<rid>/complete", methods=["POST"])
def complete_work_order(rid):
    require(["CrewLead"])
    get_body()
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not IN_PROGRESS")
    asset = DB["assets"].get(wo["asset_id"])

    # 1. Consume still-RESERVED reservations
    reservations = [r for r in DB["material_reservations"].values()
                    if r["work_order_id"] == wo["id"]]
    for r in reservations:
        if r["status"] == "RESERVED":
            item = DB["material_items"].get(r["material_item_id"])
            line = round_half_up(to_decimal(r["qty"]) * to_decimal(item["unit_cost_cents"]))
            r["consumed_cost_cents"] = line
            r["status"] = "CONSUMED"
            touch(r)
            item["on_hand_qty"] -= r["qty"]
            item["reserved_qty"] -= r["qty"]
            touch(item)

    # 2. Cost rollup (per-line rounded then summed for material)
    material_cost = 0
    for r in reservations:
        if r["status"] == "CONSUMED":
            item = DB["material_items"].get(r["material_item_id"])
            material_cost += round_half_up(to_decimal(r["qty"]) * to_decimal(item["unit_cost_cents"]))
    labor_cost = 0
    for d in DB["dispatches"].values():
        if d["work_order_id"] == wo["id"] and d["status"] != "CANCELLED":
            labor_cost += d["labor_cost_cents"]
    actual_cost = labor_cost + material_cost
    wo["labor_cost_cents"] = labor_cost
    wo["material_cost_cents"] = material_cost
    wo["actual_cost_cents"] = actual_cost

    # 3. Capitalization
    if wo["work_type"] == "CAPITAL":
        capitalized = True
    else:
        betterment_floor = round_half_up(to_decimal(asset["replacement_value_cents"]) * BETTERMENT_PCT)
        capitalized = (actual_cost >= CAPITALIZATION_THRESHOLD_CENTS
                       and actual_cost >= betterment_floor)
    wo["capitalized"] = capitalized

    # 4. Post to ledger
    if capitalized:
        asset["capital_cost_to_date_cents"] += actual_cost
    else:
        asset["maintenance_cost_to_date_cents"] += actual_cost

    # 5. Release dispatches (ACTIVE or RESERVED)
    for d in DB["dispatches"].values():
        if d["work_order_id"] == wo["id"] and d["status"] in ("ACTIVE", "RESERVED"):
            release_dispatch(d)

    # 6. Release permits (APPROVED or ACTIVE)
    for p in DB["row_permits"].values():
        if p["work_order_id"] == wo["id"] and p["status"] in ("APPROVED", "ACTIVE"):
            p["status"] = "RELEASED"
            touch(p)

    # 7. Close linked service request
    if wo["service_request_id"]:
        sr = DB["service_requests"].get(wo["service_request_id"])
        if sr is not None and sr["status"] == "LINKED":
            sr["status"] = "CLOSED"
            touch(sr)

    # 8. Return asset to service if applicable
    if asset["status"] == "UNDER_REPAIR" and not asset_has_non_terminal_wo(asset["id"], exclude_id=wo["id"]):
        asset["status"] = "ACTIVE"

    # 9. Finalize
    wo["status"] = "COMPLETED"
    touch(wo)
    touch(asset)  # completion always mutates the asset (ledger + optional status)
    return ok("work_orders", wo)


@app.route("/work-orders/<rid>/cancel", methods=["POST"])
def cancel_work_order(rid):
    require(["Dispatcher"])
    get_body()
    wo = lookup("work_orders", rid)
    check_not_terminal("work_orders", wo)
    if wo["status"] not in NON_TERMINAL_WO:
        raise ApiError("ERR_INVALID_STATE", 409, "Work order cannot be cancelled from its state")
    asset = DB["assets"].get(wo["asset_id"])
    asset_touched = False

    if wo["status"] != "DRAFT":
        # release cascade
        for d in DB["dispatches"].values():
            if d["work_order_id"] == wo["id"] and d["status"] in ("RESERVED", "ACTIVE"):
                cancel_dispatch_internal(d)
        for r in DB["material_reservations"].values():
            if r["work_order_id"] == wo["id"] and r["status"] == "RESERVED":
                item = DB["material_items"].get(r["material_item_id"])
                r["status"] = "RELEASED"
                touch(r)
                if item is not None:
                    item["reserved_qty"] -= r["qty"]
                    touch(item)
        for p in DB["row_permits"].values():
            if p["work_order_id"] == wo["id"] and p["status"] in ("APPROVED", "ACTIVE"):
                p["status"] = "RELEASED"
                touch(p)
        if asset is not None and asset["status"] == "UNDER_REPAIR" \
                and not asset_has_non_terminal_wo(asset["id"], exclude_id=wo["id"]):
            asset["status"] = "ACTIVE"
            asset_touched = True

    wo["status"] = "CANCELLED"
    touch(wo)
    if asset_touched:
        touch(asset)
    return ok("work_orders", wo)


# ===========================================================================
# CREW endpoints
# ===========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    require(["Supervisor"])
    body = get_body()
    name = req_str(body, "name")
    crew_type = req_enum(body, "crew_type")
    hourly_rate_cents = req_int(body, "hourly_rate_cents", minimum=0)
    rec = new_record({
        "name": name,
        "crew_type": crew_type,
        "hourly_rate_cents": hourly_rate_cents,
        "status": "AVAILABLE",
        "committed_minutes": 0,
    })
    DB["crews"][rec["id"]] = rec
    return ok("crews", rec, 201)


@app.route("/crews/<rid>", methods=["GET"])
def get_crew(rid):
    require(ALL_ROLES)
    return ok("crews", lookup("crews", rid))


@app.route("/crews", methods=["GET"])
def list_crews():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter("crews", ["crew_type", "status"])
    return ok_list("crews", page, limit, offset, total)


# ===========================================================================
# DISPATCH endpoints
# ===========================================================================
@app.route("/dispatches", methods=["POST"])
def create_dispatch():
    require(["Dispatcher"])
    body = get_body()
    labor_hours = req_number(body, "labor_hours", exclusive_min=0)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        validation_error("window_end must be after window_start")
    if "expected_crew_version" not in body or body["expected_crew_version"] is None:
        validation_error("Missing required field: expected_crew_version")
    expected_crew_version = req_int(body, "expected_crew_version")
    # existence: work_order_id then crew_id
    if "work_order_id" not in body or body["work_order_id"] is None:
        validation_error("Missing required field: work_order_id")
    wo = lookup("work_orders", body["work_order_id"])
    if "crew_id" not in body or body["crew_id"] is None:
        validation_error("Missing required field: crew_id")
    crew = lookup("crews", body["crew_id"])
    # state: WO must be SCHEDULED
    if wo["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Work order is not SCHEDULED")
    # crew window conflict (priority 13) — buffer new window 30 min each side
    buf_start = window_start - MOBILIZATION_BUFFER
    buf_end = window_end + MOBILIZATION_BUFFER
    for d in DB["dispatches"].values():
        if d["crew_id"] == crew["id"] and d["status"] in ("RESERVED", "ACTIVE"):
            if buf_start < d["window_end"] and d["window_start"] < buf_end:
                raise ApiError("ERR_CREW_WINDOW_CONFLICT", 409, "Crew window conflict")
    # OCC (priority 15)
    if expected_crew_version != crew["version"]:
        raise ApiError("ERR_STALE_CREW_VERSION", 412, "Stale crew version")

    labor_cost = compute_labor_cost(labor_hours, crew["hourly_rate_cents"])
    rec = new_record({
        "work_order_id": wo["id"],
        "crew_id": crew["id"],
        "window_start": window_start,
        "window_end": window_end,
        "labor_hours": labor_hours,
        "labor_cost_cents": labor_cost,
        "status": "RESERVED",
    })
    DB["dispatches"][rec["id"]] = rec
    crew["status"] = "ON_ASSIGNMENT"
    crew["committed_minutes"] += window_minutes(window_start, window_end)
    touch(crew)
    return ok("dispatches", rec, 201)


@app.route("/dispatches/<rid>", methods=["GET"])
def get_dispatch(rid):
    require(ALL_ROLES)
    return ok("dispatches", lookup("dispatches", rid))


@app.route("/dispatches", methods=["GET"])
def list_dispatches():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "dispatches", ["work_order_id", "crew_id", "status"])
    return ok_list("dispatches", page, limit, offset, total)


@app.route("/dispatches/<rid>/cancel", methods=["POST"])
def cancel_dispatch(rid):
    require(["Dispatcher"])
    get_body()
    d = lookup("dispatches", rid)
    check_not_terminal("dispatches", d)
    if d["status"] not in ("RESERVED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Dispatch cannot be cancelled from its state")
    cancel_dispatch_internal(d)
    return ok("dispatches", d)


# ===========================================================================
# YARD endpoints
# ===========================================================================
@app.route("/yards", methods=["POST"])
def create_yard():
    require(["Supervisor"])
    body = get_body()
    name = req_str(body, "name")
    location_desc = req_str(body, "location_desc")
    rec = new_record({"name": name, "location_desc": location_desc})
    DB["yards"][rec["id"]] = rec
    return ok("yards", rec, 201)


@app.route("/yards/<rid>", methods=["GET"])
def get_yard(rid):
    require(ALL_ROLES)
    return ok("yards", lookup("yards", rid))


@app.route("/yards", methods=["GET"])
def list_yards():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter("yards", [])
    return ok_list("yards", page, limit, offset, total)


# ===========================================================================
# MATERIAL ITEM endpoints
# ===========================================================================
@app.route("/material-items", methods=["POST"])
def create_material_item():
    require(["Supervisor"])
    body = get_body()
    material_type = req_enum(body, "material_type")
    unit = req_str(body, "unit")
    on_hand_qty = req_number(body, "on_hand_qty", minimum=0)
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)
    reorder_point = opt_int(body, "reorder_point", 0, minimum=0)
    if "yard_id" not in body or body["yard_id"] is None:
        validation_error("Missing required field: yard_id")
    yard = lookup("yards", body["yard_id"])
    rec = new_record({
        "material_type": material_type,
        "yard_id": yard["id"],
        "unit": unit,
        "on_hand_qty": on_hand_qty,
        "reserved_qty": 0,
        "unit_cost_cents": unit_cost_cents,
        "reorder_point": reorder_point,
    })
    DB["material_items"][rec["id"]] = rec
    return ok("material_items", rec, 201)


@app.route("/material-items/<rid>", methods=["GET"])
def get_material_item(rid):
    require(ALL_ROLES)
    return ok("material_items", lookup("material_items", rid))


@app.route("/material-items", methods=["GET"])
def list_material_items():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "material_items", ["material_type", "yard_id"])
    return ok_list("material_items", page, limit, offset, total)


@app.route("/material-items/<rid>/restock", methods=["POST"])
def restock_material_item(rid):
    require(["Supervisor"])
    body = get_body()
    qty = req_number(body, "qty", exclusive_min=0)
    item = lookup("material_items", rid)
    item["on_hand_qty"] += qty
    touch(item)
    return ok("material_items", item)


# ===========================================================================
# MATERIAL RESERVATION endpoints
# ===========================================================================
@app.route("/material-reservations", methods=["POST"])
def create_material_reservation():
    require(["Dispatcher", "CrewLead"])
    body = get_body()
    qty = req_number(body, "qty", exclusive_min=0)
    if "expected_material_item_version" not in body or body["expected_material_item_version"] is None:
        validation_error("Missing required field: expected_material_item_version")
    expected_version = req_int(body, "expected_material_item_version")
    # existence: work_order_id then material_item_id
    if "work_order_id" not in body or body["work_order_id"] is None:
        validation_error("Missing required field: work_order_id")
    wo = lookup("work_orders", body["work_order_id"])
    if "material_item_id" not in body or body["material_item_id"] is None:
        validation_error("Missing required field: material_item_id")
    item = lookup("material_items", body["material_item_id"])
    # state (priority 10)
    if wo["status"] not in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS", "ON_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "Work order cannot receive reservations in its state")
    # OCC (priority 15)
    if expected_version != item["version"]:
        raise ApiError("ERR_STALE_MATERIAL_VERSION", 412, "Stale material item version")
    # sufficiency (priority 16)
    available = item["on_hand_qty"] - item["reserved_qty"]
    if qty > available:
        raise ApiError("ERR_INSUFFICIENT_MATERIAL", 409, "Insufficient material available")

    rec = new_record({
        "work_order_id": wo["id"],
        "material_item_id": item["id"],
        "qty": qty,
        "consumed_cost_cents": 0,
        "status": "RESERVED",
    })
    DB["material_reservations"][rec["id"]] = rec
    item["reserved_qty"] += qty
    touch(item)
    return ok("material_reservations", rec, 201)


@app.route("/material-reservations/<rid>", methods=["GET"])
def get_material_reservation(rid):
    require(ALL_ROLES)
    return ok("material_reservations", lookup("material_reservations", rid))


@app.route("/material-reservations", methods=["GET"])
def list_material_reservations():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "material_reservations", ["work_order_id", "material_item_id", "status"])
    return ok_list("material_reservations", page, limit, offset, total)


@app.route("/material-reservations/<rid>/release", methods=["POST"])
def release_material_reservation(rid):
    require(["Dispatcher", "CrewLead"])
    get_body()
    r = lookup("material_reservations", rid)
    check_not_terminal("material_reservations", r)
    if r["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation is not RESERVED")
    item = DB["material_items"].get(r["material_item_id"])
    r["status"] = "RELEASED"
    touch(r)
    if item is not None:
        item["reserved_qty"] -= r["qty"]
        touch(item)
    return ok("material_reservations", r)


# ===========================================================================
# ROW PERMIT endpoints
# ===========================================================================
@app.route("/row-permits", methods=["POST"])
def create_row_permit():
    require(["Coordinator"])
    body = get_body()
    permit_type = req_enum(body, "permit_type")
    gis_segment_id = req_str(body, "gis_segment_id")
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        validation_error("window_end must be after window_start")
    clearance_required = opt_bool(body, "clearance_required", True)
    utility_company = body.get("utility_company")
    if utility_company is not None and not isinstance(utility_company, str):
        validation_error("utility_company must be a string")
    if "work_order_id" not in body or body["work_order_id"] is None:
        validation_error("Missing required field: work_order_id")
    wo = lookup("work_orders", body["work_order_id"])
    rec = new_record({
        "work_order_id": wo["id"],
        "permit_type": permit_type,
        "gis_segment_id": gis_segment_id,
        "utility_company": utility_company,
        "window_start": window_start,
        "window_end": window_end,
        "clearance_required": clearance_required,
        "status": "REQUESTED",
    })
    DB["row_permits"][rec["id"]] = rec
    return ok("row_permits", rec, 201)


@app.route("/row-permits/<rid>", methods=["GET"])
def get_row_permit(rid):
    require(ALL_ROLES)
    return ok("row_permits", lookup("row_permits", rid))


@app.route("/row-permits", methods=["GET"])
def list_row_permits():
    require(ALL_ROLES)
    page, limit, offset, total = paginate_and_filter(
        "row_permits", ["work_order_id", "status", "gis_segment_id"])
    return ok_list("row_permits", page, limit, offset, total)


@app.route("/row-permits/<rid>/decision", methods=["POST"])
def decide_row_permit(rid):
    require(["Coordinator"])
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("APPROVE", "DENY"):
        validation_error("decision must be APPROVE or DENY")
    permit = lookup("row_permits", rid)
    check_not_terminal("row_permits", permit)
    if permit["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Permit is not REQUESTED")
    if decision == "DENY":
        permit["status"] = "DENIED"
        touch(permit)
        return ok("row_permits", permit)
    # APPROVE — segment conflict check (priority 14, closed interval, adjacency intersects)
    for other in DB["row_permits"].values():
        if other["id"] == permit["id"]:
            continue
        if other["gis_segment_id"] != permit["gis_segment_id"]:
            continue
        if other["status"] in ("APPROVED", "ACTIVE"):
            if permit["window_start"] <= other["window_end"] and other["window_start"] <= permit["window_end"]:
                raise ApiError("ERR_ROW_SEGMENT_CONFLICT", 409, "ROW segment window conflict")
    permit["status"] = "APPROVED"
    touch(permit)
    return ok("row_permits", permit)


@app.route("/row-permits/<rid>/release", methods=["POST"])
def release_row_permit(rid):
    require(["Coordinator"])
    get_body()
    permit = lookup("row_permits", rid)
    check_not_terminal("row_permits", permit)
    if permit["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Permit is not APPROVED or ACTIVE")
    permit["status"] = "RELEASED"
    touch(permit)
    return ok("row_permits", permit)


# ===========================================================================
# LOGICAL CLOCK endpoint
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(ALL_ROLES)
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        validation_error("Missing required field: to_iso8601")
    try:
        dt = parse_iso(body["to_iso8601"])
    except Exception:
        validation_error("to_iso8601 must be a valid ISO-8601 datetime")
    CLOCK["now"] = dt
    return ok_empty(200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
