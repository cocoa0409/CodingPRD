import os
import re
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"IntakeClerk", "ScreeningOfficer", "AssignmentCoordinator",
         "SupervisingAttorney", "Attorney"}
ALL_ROLES = list(ROLES)

CHARGE_CLASSES = {"FELONY_A", "FELONY_B", "MISDEMEANOR", "JUVENILE", "APPEAL"}
ATTORNEY_TYPES = {"STAFF", "PANEL"}
RECOUPMENT_BASES = {"SCHEDULE", "ACTUAL"}
DISPOSITION_TYPES = {"DISMISSED", "PLEA", "ACQUITTAL", "CONVICTION"}
COMPLEXITY_TIERS = {"STANDARD", "COMPLEX", "CAPITAL"}
EVENT_TYPES = {"ARRAIGNMENT", "MOTION_HEARING", "PRETRIAL", "TRIAL", "SENTENCING"}
SERVICE_TYPES = {"INVESTIGATOR", "EXPERT_PSYCH", "EXPERT_FORENSIC"}
VOUCHER_TYPES = {"PANEL_FEE", "SERVICE"}

BASE_WEIGHT = {
    "FELONY_A": Decimal("4.0"), "FELONY_B": Decimal("2.5"),
    "MISDEMEANOR": Decimal("1.0"), "JUVENILE": Decimal("1.5"),
    "APPEAL": Decimal("3.0"),
}
COMPLEXITY_MULT = {"STANDARD": Decimal("1.0"), "COMPLEX": Decimal("1.5"),
                   "CAPITAL": Decimal("2.0")}
CO_DEF_INCREMENT = Decimal("0.25")

CASE_FEE_CAP = {"FELONY_A": 750000, "FELONY_B": 500000, "MISDEMEANOR": 200000,
                "JUVENILE": 300000, "APPEAL": 600000}
SERVICE_CAP = {"INVESTIGATOR": 250000, "EXPERT_PSYCH": 500000,
               "EXPERT_FORENSIC": 750000}
RECOUP_SCHEDULE = {"FELONY_A": 50000, "FELONY_B": 40000, "MISDEMEANOR": 15000,
                   "JUVENILE": 10000, "APPEAL": 35000}

FPL_BASE_CENTS = 1500000
FPL_INCREMENT_CENTS = 500000
ELIGIBLE_MULT = Decimal("1.25")
PARTIAL_MULT = Decimal("2.00")
ASSET_INELIGIBLE_CAP_CENTS = 2000000
ASSET_CONTRIB_FLOOR_CENTS = 500000
INCOME_RATE = Decimal("0.10")
ASSET_RATE = Decimal("0.05")

TRAVEL_BUFFER = timedelta(minutes=30)

# ---------------------------------------------------------------------------
# In-memory store  (empty on every boot; nothing is seeded)
# ---------------------------------------------------------------------------
DB = {
    "offices": {},
    "attorneys": {},
    "courtrooms": {},
    "cases": {},
    "screenings": {},
    "conflict_checks": {},
    "assignments": {},
    "court_events": {},
    "service_requests": {},
    "vouchers": {},
    "recoupment_orders": {},
}
_seq_counter = [0]
LOGICAL_CLOCK = [datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


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
# Time / formatting helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def clock_iso():
    return fmt_dt(LOGICAL_CLOCK[0])


def parse_iso(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {"api_request_id": getattr(g, "request_id", gen_request_id()),
         "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def to_json_value(v):
    if isinstance(v, Decimal):
        f = float(v)
        return f
    return v


def envelope(data, response_type="object", pagination=None):
    return {"meta": _meta(pagination), "response_type": response_type,
            "data": data}


def ok(data, status=200):
    return jsonify(envelope(data, "object")), status


def ok_list(items, pagination):
    return jsonify(envelope(items, "array", pagination)), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"}}
    return jsonify(body), 405


@app.before_request
def _assign_request_id():
    g.request_id = gen_request_id()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", 400,
                       "Missing or invalid user context headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def v_error(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        v_error(f"Field '{name}' must be a non-empty string")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        v_error(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_int(body, name, min_v=None, min_exclusive=False):
    v = body.get(name)
    if not is_int(v):
        v_error(f"Field '{name}' must be an integer")
    if min_v is not None:
        if min_exclusive and not v > min_v:
            v_error(f"Field '{name}' must be > {min_v}")
        if not min_exclusive and v < min_v:
            v_error(f"Field '{name}' must be >= {min_v}")
    return v


def req_num(body, name, min_v=None, min_exclusive=False):
    v = body.get(name)
    if not is_num(v):
        v_error(f"Field '{name}' must be a number")
    if min_v is not None:
        if min_exclusive and not v > min_v:
            v_error(f"Field '{name}' must be > {min_v}")
        if not min_exclusive and v < min_v:
            v_error(f"Field '{name}' must be >= {min_v}")
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def must_get(collection, key, err_id):
    obj = DB[collection].get(key)
    if obj is None:
        raise ApiError(err_id, 404, f"{err_id}")
    return obj


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up_int(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_dec(v):
    return Decimal(str(v))


# ---------------------------------------------------------------------------
# Entity creation
# ---------------------------------------------------------------------------
def new_common(with_version=True):
    ts = now_iso()
    base = {"id": str(uuid.uuid4()), "created_at": ts, "_seq": next_seq()}
    if with_version:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def bump(entity):
    entity["updated_at"] = now_iso()
    if "version" in entity:
        entity["version"] += 1


# ---------------------------------------------------------------------------
# Derived / aggregate helpers
# ---------------------------------------------------------------------------
def active_assignment_for_case(case_id):
    for a in DB["assignments"].values():
        if a["case_id"] == case_id and a["status"] == "ACTIVE":
            return a
    return None


def assigned_attorney_id(case_id):
    a = active_assignment_for_case(case_id)
    return a["attorney_id"] if a else None


def recompute_attorney_status(att):
    if att["status"] == "SUSPENDED":
        return
    if att["current_weighted_load"] >= att["max_weighted_caseload"]:
        att["status"] = "AT_CAPACITY"
    else:
        att["status"] = "ACTIVE"


def recompute_budget_status(office):
    threshold = to_dec(office["annual_voucher_budget_cents"]) * Decimal("0.90")
    if to_dec(office["voucher_spent_cents"]) > threshold:
        office["budget_status"] = "RESTRICTED"
    else:
        office["budget_status"] = "OPEN"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(entity, kind):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = to_json_value(v)
    if kind == "case":
        out["assigned_attorney_id"] = assigned_attorney_id(entity["id"])
    return out


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            v_error("limit must be an integer")
        if limit < 1 or limit > 100:
            v_error("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            v_error("offset must be an integer")
        if offset < 0:
            v_error("offset must be >= 0")
    return limit, offset


def list_response(collection, kind, filters):
    limit, offset = parse_pagination()
    items = list(DB[collection].values())
    for fk, fv in filters.items():
        if fv is not None:
            items = [it for it in items if str(it.get(fk)) == str(fv)]
    items.sort(key=lambda it: it["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}
    return ok_list([serialize(it, kind) for it in page], pagination)


# ===========================================================================
# DefenderOffice
# ===========================================================================
@app.route("/defender-offices", methods=["POST"])
def create_office():
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    body = get_body()
    name = req_str(body, "name")
    budget = req_int(body, "annual_voucher_budget_cents", min_v=0, min_exclusive=True)
    basis = "SCHEDULE"
    if "recoupment_basis" in body and body.get("recoupment_basis") is not None:
        basis = req_enum(body, "recoupment_basis", RECOUPMENT_BASES)
    office = new_common()
    office.update({
        "name": name,
        "annual_voucher_budget_cents": budget,
        "recoupment_basis": basis,
        "voucher_spent_cents": 0,
        "budget_status": "OPEN",
    })
    DB["offices"][office["id"]] = office
    return ok(serialize(office, "office"), 201)


@app.route("/defender-offices/<office_id>", methods=["GET"])
def get_office(office_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    office = must_get("offices", office_id, "ERR_OFFICE_NOT_FOUND")
    return ok(serialize(office, "office"))


# ===========================================================================
# Attorney
# ===========================================================================
@app.route("/attorneys", methods=["POST"])
def create_attorney():
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    body = get_body()
    # existence of office_id FK (if present)
    if body.get("office_id") is not None:
        must_get("offices", body.get("office_id"), "ERR_OFFICE_NOT_FOUND")
    office_id = req_str(body, "office_id")
    name = req_str(body, "name")
    atype = req_enum(body, "attorney_type", ATTORNEY_TYPES)
    bar_number = req_str(body, "bar_number")
    hourly_rate = req_int(body, "hourly_rate_cents", min_v=0)
    max_load = req_num(body, "max_weighted_caseload", min_v=0, min_exclusive=True)
    att = new_common()
    att.update({
        "office_id": office_id,
        "name": name,
        "attorney_type": atype,
        "bar_number": bar_number,
        "hourly_rate_cents": hourly_rate,
        "max_weighted_caseload": to_dec(max_load),
        "current_weighted_load": Decimal("0"),
        "status": "ACTIVE",
    })
    DB["attorneys"][att["id"]] = att
    return ok(serialize(att, "attorney"), 201)


@app.route("/attorneys/<attorney_id>", methods=["GET"])
def get_attorney(attorney_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    att = must_get("attorneys", attorney_id, "ERR_ATTORNEY_NOT_FOUND")
    return ok(serialize(att, "attorney"))


@app.route("/attorneys", methods=["GET"])
def list_attorneys():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"office_id": request.args.get("office_id"),
               "status": request.args.get("status")}
    return list_response("attorneys", "attorney", filters)


@app.route("/attorneys/<attorney_id>/suspend", methods=["POST"])
def suspend_attorney(attorney_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    att = must_get("attorneys", attorney_id, "ERR_ATTORNEY_NOT_FOUND")
    if att["status"] == "SUSPENDED":
        raise ApiError("ERR_ATTORNEY_NOT_ACTIVE", 409, "Attorney already suspended")
    att["status"] = "SUSPENDED"
    bump(att)
    return ok(serialize(att, "attorney"))


@app.route("/attorneys/<attorney_id>/reactivate", methods=["POST"])
def reactivate_attorney(attorney_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    att = must_get("attorneys", attorney_id, "ERR_ATTORNEY_NOT_FOUND")
    if att["status"] != "SUSPENDED":
        raise ApiError("ERR_ATTORNEY_NOT_ACTIVE", 409, "Attorney is not suspended")
    if att["current_weighted_load"] >= att["max_weighted_caseload"]:
        att["status"] = "AT_CAPACITY"
    else:
        att["status"] = "ACTIVE"
    bump(att)
    return ok(serialize(att, "attorney"))


# ===========================================================================
# Courtroom
# ===========================================================================
@app.route("/courtrooms", methods=["POST"])
def create_courtroom():
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    body = get_body()
    name = req_str(body, "name")
    courthouse = req_str(body, "courthouse")
    room = new_common(with_version=False)
    room.update({"name": name, "courthouse": courthouse})
    DB["courtrooms"][room["id"]] = room
    return ok(serialize(room, "courtroom"), 201)


@app.route("/courtrooms/<courtroom_id>", methods=["GET"])
def get_courtroom(courtroom_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    room = must_get("courtrooms", courtroom_id, "ERR_COURTROOM_NOT_FOUND")
    return ok(serialize(room, "courtroom"))


# ===========================================================================
# Case
# ===========================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    _, role = require_auth()
    require_role(role, ["IntakeClerk"])
    body = get_body()
    if body.get("office_id") is not None:
        must_get("offices", body.get("office_id"), "ERR_OFFICE_NOT_FOUND")
    office_id = req_str(body, "office_id")
    defendant_name = req_str(body, "defendant_name")
    charge_class = req_enum(body, "charge_class", CHARGE_CLASSES)
    case = new_common()
    case.update({
        "office_id": office_id,
        "defendant_name": defendant_name,
        "charge_class": charge_class,
        "status": "REFERRED",
        "eligibility_status": "PENDING",
        "case_weight": Decimal("0"),
        "weight_basis": "PROVISIONAL",
        "complexity_tier": "STANDARD",
        "co_defendant_count": 0,
        "disposition_type": None,
        "disposition_date": None,
    })
    DB["cases"][case["id"]] = case
    return ok(serialize(case, "case"), 201)


@app.route("/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    case = must_get("cases", case_id, "ERR_CASE_NOT_FOUND")
    return ok(serialize(case, "case"))


@app.route("/cases", methods=["GET"])
def list_cases():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"office_id": request.args.get("office_id"),
               "status": request.args.get("status")}
    return list_response("cases", "case", filters)


@app.route("/cases/<case_id>/reassign", methods=["POST"])
def reassign_case(case_id):
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    case = must_get("cases", case_id, "ERR_CASE_NOT_FOUND")
    body = get_body()
    # body FK existence
    if body.get("new_attorney_id") is not None:
        must_get("attorneys", body.get("new_attorney_id"), "ERR_ATTORNEY_NOT_FOUND")
    new_attorney_id = req_str(body, "new_attorney_id")
    expected_version = req_int(body, "expected_case_version")
    # state
    if case["status"] != "ASSIGNED":
        raise ApiError("ERR_CASE_NOT_ASSIGNED", 409, "Case is not ASSIGNED")
    # OCC
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION", 412, "Stale case version")
    new_att = DB["attorneys"][new_attorney_id]
    if new_att["status"] == "SUSPENDED":
        raise ApiError("ERR_ATTORNEY_NOT_ACTIVE", 409, "Attorney suspended")
    if not has_clear_conflict(case_id, new_attorney_id):
        raise ApiError("ERR_CONFLICT_NOT_CLEARED", 409, "No CLEAR conflict check")
    candidate = case["case_weight"]
    if new_att["current_weighted_load"] + candidate > new_att["max_weighted_caseload"]:
        raise ApiError("ERR_CASELOAD_CAPACITY_EXCEEDED", 409, "Capacity exceeded")

    prior = active_assignment_for_case(case_id)
    if prior:
        prior["status"] = "REASSIGNED"
        bump(prior)
        prior_att = DB["attorneys"].get(prior["attorney_id"])
        if prior_att:
            prior_att["current_weighted_load"] -= prior["assigned_weight"]
            recompute_attorney_status(prior_att)
            bump(prior_att)

    new_assignment = new_common()
    new_assignment.update({
        "case_id": case_id,
        "attorney_id": new_attorney_id,
        "assigned_weight": candidate,
        "status": "ACTIVE",
    })
    DB["assignments"][new_assignment["id"]] = new_assignment
    new_att["current_weighted_load"] += candidate
    recompute_attorney_status(new_att)
    bump(new_att)

    bump(case)  # increments version by one
    return ok(serialize(case, "case"))


@app.route("/cases/<case_id>/adjust-weight", methods=["POST"])
def adjust_weight(case_id):
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    case = must_get("cases", case_id, "ERR_CASE_NOT_FOUND")
    body = get_body()
    tier = req_enum(body, "complexity_tier", COMPLEXITY_TIERS)
    co_def = req_int(body, "co_defendant_count", min_v=0)
    if case["status"] != "ASSIGNED":
        raise ApiError("ERR_CASE_NOT_ASSIGNED", 409, "Case is not ASSIGNED")
    assignment = active_assignment_for_case(case_id)
    if assignment is None:
        raise ApiError("ERR_CASE_NOT_ASSIGNED", 409, "No active assignment")
    att = DB["attorneys"][assignment["attorney_id"]]
    new_weight = (BASE_WEIGHT[case["charge_class"]] * COMPLEXITY_MULT[tier]
                  + CO_DEF_INCREMENT * co_def)
    new_weight = new_weight.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    load_excluding = att["current_weighted_load"] - assignment["assigned_weight"]
    if load_excluding + new_weight > att["max_weighted_caseload"]:
        raise ApiError("ERR_CASELOAD_CAPACITY_EXCEEDED", 409, "Capacity exceeded")
    case["case_weight"] = new_weight
    case["weight_basis"] = "ACTUAL"
    case["complexity_tier"] = tier
    case["co_defendant_count"] = co_def
    bump(case)
    assignment["assigned_weight"] = new_weight
    bump(assignment)
    att["current_weighted_load"] = load_excluding + new_weight
    recompute_attorney_status(att)
    bump(att)
    return ok(serialize(case, "case"))


@app.route("/cases/<case_id>/dispose", methods=["POST"])
def dispose_case(case_id):
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    case = must_get("cases", case_id, "ERR_CASE_NOT_FOUND")
    body = get_body()
    disposition_type = req_enum(body, "disposition_type", DISPOSITION_TYPES)
    if case["status"] != "ASSIGNED":
        raise ApiError("ERR_CASE_NOT_ASSIGNED", 409, "Case is not ASSIGNED")
    case["status"] = "DISPOSED"
    case["disposition_type"] = disposition_type
    case["disposition_date"] = clock_iso()
    bump(case)
    # cascade: close active assignment
    assignment = active_assignment_for_case(case_id)
    if assignment:
        assignment["status"] = "CLOSED"
        bump(assignment)
        att = DB["attorneys"].get(assignment["attorney_id"])
        if att:
            att["current_weighted_load"] -= assignment["assigned_weight"]
            recompute_attorney_status(att)
            bump(att)
    # recoupment on PARTIAL screening
    screening = decided_screening_for_case(case_id)
    if screening and screening["result"] == "PARTIAL":
        office = DB["offices"].get(case["office_id"])
        basis = office["recoupment_basis"] if office else "SCHEDULE"
        if basis == "SCHEDULE":
            assessed = RECOUP_SCHEDULE[case["charge_class"]]
        else:
            assessed = screening["contribution_amount_cents"]
        order = new_common()
        order.update({
            "case_id": case_id,
            "basis": basis,
            "assessed_amount_cents": assessed,
            "collected_amount_cents": 0,
            "status": "ASSESSED",
            "waived_by_user_id": None,
        })
        DB["recoupment_orders"][order["id"]] = order
    return ok(serialize(case, "case"))


# ===========================================================================
# FinancialScreening
# ===========================================================================
def decided_screening_for_case(case_id):
    for s in DB["screenings"].values():
        if s["case_id"] == case_id and s["status"] == "DECIDED":
            return s
    return None


@app.route("/financial-screenings", methods=["POST"])
def create_screening():
    _, role = require_auth()
    require_role(role, ["IntakeClerk"])
    body = get_body()
    if body.get("case_id") is not None:
        must_get("cases", body.get("case_id"), "ERR_CASE_NOT_FOUND")
    case_id = req_str(body, "case_id")
    income = req_int(body, "household_income_cents", min_v=0)
    size = req_int(body, "household_size", min_v=1)
    assets = req_int(body, "asset_value_cents", min_v=0)
    # uniqueness
    for s in DB["screenings"].values():
        if s["case_id"] == case_id:
            raise ApiError("ERR_SCREENING_ALREADY_EXISTS", 409,
                           "Screening already exists for case")
    screening = new_common()
    screening.update({
        "case_id": case_id,
        "household_income_cents": income,
        "household_size": size,
        "asset_value_cents": assets,
        "status": "SUBMITTED",
        "result": "PENDING",
        "contribution_amount_cents": 0,
        "decided_by_user_id": None,
    })
    DB["screenings"][screening["id"]] = screening
    return ok(serialize(screening, "screening"), 201)


@app.route("/financial-screenings/<screening_id>", methods=["GET"])
def get_screening(screening_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    s = must_get("screenings", screening_id, "ERR_SCREENING_NOT_FOUND")
    return ok(serialize(s, "screening"))


@app.route("/financial-screenings", methods=["GET"])
def list_screenings():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id")}
    return list_response("screenings", "screening", filters)


@app.route("/financial-screenings/<screening_id>/decide", methods=["POST"])
def decide_screening(screening_id):
    uid, role = require_auth()
    require_role(role, ["ScreeningOfficer"])
    s = must_get("screenings", screening_id, "ERR_SCREENING_NOT_FOUND")
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_SCREENING_ALREADY_DECIDED", 409, "Already decided")
    fpl = FPL_BASE_CENTS + (s["household_size"] - 1) * FPL_INCREMENT_CENTS
    eligible_ceiling = to_dec(fpl) * ELIGIBLE_MULT
    partial_ceiling = to_dec(fpl) * PARTIAL_MULT
    income = to_dec(s["household_income_cents"])
    if s["asset_value_cents"] > ASSET_INELIGIBLE_CAP_CENTS:
        result = "INELIGIBLE"
    elif income <= eligible_ceiling:
        result = "ELIGIBLE"
    elif income <= partial_ceiling:
        result = "PARTIAL"
    else:
        result = "INELIGIBLE"

    contribution = 0
    if result == "PARTIAL":
        # income_excess uses round(fpl * ELIGIBLE_MULT) as the ceiling
        ceiling = int(eligible_ceiling.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        income_excess = s["household_income_cents"] - ceiling
        asset_excess = max(0, s["asset_value_cents"] - ASSET_CONTRIB_FLOOR_CENTS)
        comp_income = round_half_up_int(to_dec(income_excess) * INCOME_RATE)
        comp_asset = round_half_up_int(to_dec(asset_excess) * ASSET_RATE)
        contribution = comp_income + comp_asset

    s["status"] = "DECIDED"
    s["result"] = result
    s["contribution_amount_cents"] = contribution
    s["decided_by_user_id"] = uid
    bump(s)

    case = DB["cases"].get(s["case_id"])
    if case:
        case["eligibility_status"] = result
        if result in ("ELIGIBLE", "PARTIAL"):
            case["status"] = "SCREENED"
        else:
            case["status"] = "DENIED"
        bump(case)
    return ok(serialize(s, "screening"))


# ===========================================================================
# ConflictCheck
# ===========================================================================
def has_clear_conflict(case_id, attorney_id):
    for c in DB["conflict_checks"].values():
        if (c["case_id"] == case_id and c["attorney_id"] == attorney_id
                and c["result"] == "CLEAR"):
            return True
    return False


@app.route("/conflict-checks", methods=["POST"])
def create_conflict_check():
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    body = get_body()
    if body.get("case_id") is not None:
        must_get("cases", body.get("case_id"), "ERR_CASE_NOT_FOUND")
    if body.get("attorney_id") is not None:
        must_get("attorneys", body.get("attorney_id"), "ERR_ATTORNEY_NOT_FOUND")
    case_id = req_str(body, "case_id")
    attorney_id = req_str(body, "attorney_id")
    co_names = body.get("co_defendant_names", [])
    if co_names is None:
        co_names = []
    if not isinstance(co_names, list) or not all(isinstance(x, str) for x in co_names):
        v_error("co_defendant_names must be an array of strings")
    # compute result
    adverse = set()
    for a in DB["assignments"].values():
        if a["attorney_id"] == attorney_id and a["status"] == "ACTIVE" \
                and a["case_id"] != case_id:
            other = DB["cases"].get(a["case_id"])
            if other:
                adverse.add(other["defendant_name"])
    result = "CONFLICT" if any(n in adverse for n in co_names) else "CLEAR"
    check = new_common(with_version=False)
    check.update({
        "case_id": case_id,
        "attorney_id": attorney_id,
        "co_defendant_names": list(co_names),
        "result": result,
    })
    DB["conflict_checks"][check["id"]] = check
    return ok(serialize(check, "conflict_check"), 201)


@app.route("/conflict-checks/<check_id>", methods=["GET"])
def get_conflict_check(check_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    c = must_get("conflict_checks", check_id, "ERR_CONFLICT_CHECK_NOT_FOUND")
    return ok(serialize(c, "conflict_check"))


@app.route("/conflict-checks", methods=["GET"])
def list_conflict_checks():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id"),
               "attorney_id": request.args.get("attorney_id")}
    return list_response("conflict_checks", "conflict_check", filters)


# ===========================================================================
# Assignment
# ===========================================================================
@app.route("/assignments", methods=["POST"])
def create_assignment():
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    body = get_body()
    if body.get("case_id") is not None:
        must_get("cases", body.get("case_id"), "ERR_CASE_NOT_FOUND")
    if body.get("attorney_id") is not None:
        must_get("attorneys", body.get("attorney_id"), "ERR_ATTORNEY_NOT_FOUND")
    case_id = req_str(body, "case_id")
    attorney_id = req_str(body, "attorney_id")
    case = DB["cases"][case_id]
    att = DB["attorneys"][attorney_id]
    if case["status"] != "SCREENED":
        raise ApiError("ERR_CASE_NOT_SCREENED", 409, "Case is not SCREENED")
    if att["status"] == "SUSPENDED":
        raise ApiError("ERR_ATTORNEY_NOT_ACTIVE", 409, "Attorney suspended")
    if not has_clear_conflict(case_id, attorney_id):
        raise ApiError("ERR_CONFLICT_NOT_CLEARED", 409, "No CLEAR conflict check")
    provisional = BASE_WEIGHT[case["charge_class"]]
    if att["current_weighted_load"] + provisional > att["max_weighted_caseload"]:
        raise ApiError("ERR_CASELOAD_CAPACITY_EXCEEDED", 409, "Capacity exceeded")

    assignment = new_common()
    assignment.update({
        "case_id": case_id,
        "attorney_id": attorney_id,
        "assigned_weight": provisional,
        "status": "ACTIVE",
    })
    DB["assignments"][assignment["id"]] = assignment

    case["case_weight"] = provisional
    case["weight_basis"] = "PROVISIONAL"
    case["status"] = "ASSIGNED"
    bump(case)

    att["current_weighted_load"] += provisional
    recompute_attorney_status(att)
    bump(att)
    return ok(serialize(assignment, "assignment"), 201)


@app.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    a = must_get("assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    return ok(serialize(a, "assignment"))


@app.route("/assignments", methods=["GET"])
def list_assignments():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id"),
               "attorney_id": request.args.get("attorney_id"),
               "status": request.args.get("status")}
    return list_response("assignments", "assignment", filters)


# ===========================================================================
# CourtEvent
# ===========================================================================
def intervals_overlap(s1, e1, s2, e2):
    # half-open [s, e)
    return s1 < e2 and s2 < e1


@app.route("/court-events", methods=["POST"])
def create_court_event():
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    body = get_body()
    if body.get("case_id") is not None:
        must_get("cases", body.get("case_id"), "ERR_CASE_NOT_FOUND")
    if body.get("courtroom_id") is not None:
        must_get("courtrooms", body.get("courtroom_id"), "ERR_COURTROOM_NOT_FOUND")
    case_id = req_str(body, "case_id")
    courtroom_id = req_str(body, "courtroom_id")
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    try:
        start_dt = parse_iso(start_raw)
    except (ValueError, TypeError):
        v_error("scheduled_start must be a valid ISO 8601 datetime")
    try:
        end_dt = parse_iso(end_raw)
    except (ValueError, TypeError):
        v_error("scheduled_end must be a valid ISO 8601 datetime")
    if not end_dt > start_dt:
        v_error("scheduled_end must be strictly after scheduled_start")

    case = DB["cases"][case_id]
    if case["status"] != "ASSIGNED":
        raise ApiError("ERR_CASE_NOT_ASSIGNED", 409, "Case is not ASSIGNED")
    att_id = assigned_attorney_id(case_id)

    if start_dt < LOGICAL_CLOCK[0]:
        raise ApiError("ERR_EVENT_IN_PAST", 409, "Event start is in the past")

    # attorney calendar buffer
    for ev in DB["court_events"].values():
        if ev["status"] != "SCHEDULED":
            continue
        if ev["attorney_id"] != att_id:
            continue
        o_start = parse_iso(ev["scheduled_start"])
        o_end = parse_iso(ev["scheduled_end"])
        if intervals_overlap(start_dt, end_dt + TRAVEL_BUFFER,
                             o_start, o_end + TRAVEL_BUFFER):
            raise ApiError("ERR_ATTORNEY_SCHEDULE_CONFLICT", 409,
                           "Attorney schedule conflict")

    # courtroom calendar (no buffer)
    for ev in DB["court_events"].values():
        if ev["status"] != "SCHEDULED":
            continue
        if ev["courtroom_id"] != courtroom_id:
            continue
        o_start = parse_iso(ev["scheduled_start"])
        o_end = parse_iso(ev["scheduled_end"])
        if intervals_overlap(start_dt, end_dt, o_start, o_end):
            raise ApiError("ERR_COURTROOM_DOUBLE_BOOKED", 409,
                           "Courtroom double-booked")

    event = new_common()
    event.update({
        "case_id": case_id,
        "attorney_id": att_id,
        "courtroom_id": courtroom_id,
        "event_type": event_type,
        "scheduled_start": fmt_dt(start_dt),
        "scheduled_end": fmt_dt(end_dt),
        "status": "SCHEDULED",
    })
    DB["court_events"][event["id"]] = event
    return ok(serialize(event, "court_event"), 201)


@app.route("/court-events/<event_id>", methods=["GET"])
def get_court_event(event_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    ev = must_get("court_events", event_id, "ERR_COURT_EVENT_NOT_FOUND")
    return ok(serialize(ev, "court_event"))


@app.route("/court-events", methods=["GET"])
def list_court_events():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id"),
               "attorney_id": request.args.get("attorney_id"),
               "courtroom_id": request.args.get("courtroom_id"),
               "status": request.args.get("status")}
    return list_response("court_events", "court_event", filters)


@app.route("/court-events/<event_id>/vacate", methods=["POST"])
def vacate_court_event(event_id):
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    ev = must_get("court_events", event_id, "ERR_COURT_EVENT_NOT_FOUND")
    if ev["status"] != "SCHEDULED":
        raise ApiError("ERR_COURT_EVENT_NOT_SCHEDULED", 409, "Not scheduled")
    ev["status"] = "VACATED"
    bump(ev)
    return ok(serialize(ev, "court_event"))


# ===========================================================================
# ServiceRequest
# ===========================================================================
@app.route("/service-requests", methods=["POST"])
def create_service_request():
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    body = get_body()
    if body.get("case_id") is not None:
        must_get("cases", body.get("case_id"), "ERR_CASE_NOT_FOUND")
    case_id = req_str(body, "case_id")
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    est_hours = req_num(body, "estimated_hours", min_v=0, min_exclusive=True)
    est_rate = req_int(body, "estimated_rate_cents", min_v=0)
    sr = new_common()
    sr.update({
        "case_id": case_id,
        "service_type": service_type,
        "estimated_hours": est_hours,
        "estimated_rate_cents": est_rate,
        "authorized_amount_cents": 0,
        "status": "REQUESTED",
    })
    DB["service_requests"][sr["id"]] = sr
    return ok(serialize(sr, "service_request"), 201)


@app.route("/service-requests/<sr_id>", methods=["GET"])
def get_service_request(sr_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    sr = must_get("service_requests", sr_id, "ERR_SERVICE_REQUEST_NOT_FOUND")
    return ok(serialize(sr, "service_request"))


@app.route("/service-requests", methods=["GET"])
def list_service_requests():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id"),
               "status": request.args.get("status")}
    return list_response("service_requests", "service_request", filters)


@app.route("/service-requests/<sr_id>/approve", methods=["POST"])
def approve_service_request(sr_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    sr = must_get("service_requests", sr_id, "ERR_SERVICE_REQUEST_NOT_FOUND")
    if sr["status"] != "REQUESTED":
        raise ApiError("ERR_SERVICE_REQUEST_NOT_APPROVED", 409, "Wrong state")
    case = DB["cases"].get(sr["case_id"])
    if not case or case["status"] != "ASSIGNED":
        raise ApiError("ERR_CASE_NOT_ASSIGNED", 409, "Case is not ASSIGNED")
    office = DB["offices"].get(case["office_id"])
    if office and office["budget_status"] == "RESTRICTED":
        raise ApiError("ERR_BUDGET_RESTRICTED", 402, "Office budget restricted")
    gross = round_half_up_int(to_dec(sr["estimated_hours"]) * to_dec(sr["estimated_rate_cents"]))
    authorized = min(gross, SERVICE_CAP[sr["service_type"]])
    sr["authorized_amount_cents"] = authorized
    sr["status"] = "APPROVED"
    bump(sr)
    return ok(serialize(sr, "service_request"))


@app.route("/service-requests/<sr_id>/complete", methods=["POST"])
def complete_service_request(sr_id):
    _, role = require_auth()
    require_role(role, ["AssignmentCoordinator"])
    sr = must_get("service_requests", sr_id, "ERR_SERVICE_REQUEST_NOT_FOUND")
    if sr["status"] != "APPROVED":
        raise ApiError("ERR_SERVICE_REQUEST_NOT_APPROVED", 409, "Not approved")
    sr["status"] = "COMPLETED"
    bump(sr)
    return ok(serialize(sr, "service_request"))


# ===========================================================================
# Voucher
# ===========================================================================
@app.route("/vouchers", methods=["POST"])
def create_voucher():
    uid, role = require_auth()
    require_role(role, ["Attorney"])
    body = get_body()
    # ownership: attorney_id (body) must equal X-User-ID (priority 2)
    if body.get("attorney_id") is not None and body.get("attorney_id") != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Voucher attorney_id must equal caller")
    # existence
    if body.get("case_id") is not None:
        must_get("cases", body.get("case_id"), "ERR_CASE_NOT_FOUND")
    if body.get("attorney_id") is not None:
        must_get("attorneys", body.get("attorney_id"), "ERR_ATTORNEY_NOT_FOUND")
    if body.get("service_request_id") is not None:
        must_get("service_requests", body.get("service_request_id"),
                 "ERR_SERVICE_REQUEST_NOT_FOUND")
    case_id = req_str(body, "case_id")
    attorney_id = req_str(body, "attorney_id")
    voucher_type = req_enum(body, "voucher_type", VOUCHER_TYPES)
    claimed_hours = req_num(body, "claimed_hours", min_v=0, min_exclusive=True)
    service_request_id = None
    if voucher_type == "SERVICE":
        if body.get("service_request_id") is None:
            v_error("service_request_id is required for SERVICE vouchers")
        service_request_id = req_str(body, "service_request_id")
    voucher = new_common()
    voucher.update({
        "case_id": case_id,
        "attorney_id": attorney_id,
        "service_request_id": service_request_id,
        "voucher_type": voucher_type,
        "claimed_hours": claimed_hours,
        "approved_amount_cents": 0,
        "status": "DRAFT",
    })
    DB["vouchers"][voucher["id"]] = voucher
    return ok(serialize(voucher, "voucher"), 201)


@app.route("/vouchers/<voucher_id>", methods=["GET"])
def get_voucher(voucher_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    v = must_get("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    return ok(serialize(v, "voucher"))


@app.route("/vouchers", methods=["GET"])
def list_vouchers():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id"),
               "attorney_id": request.args.get("attorney_id"),
               "service_request_id": request.args.get("service_request_id"),
               "status": request.args.get("status")}
    return list_response("vouchers", "voucher", filters)


@app.route("/vouchers/<voucher_id>/submit", methods=["POST"])
def submit_voucher(voucher_id):
    uid, role = require_auth()
    require_role(role, ["Attorney"])
    v = must_get("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    if v["attorney_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not the owning attorney")
    if v["status"] != "DRAFT":
        raise ApiError("ERR_VOUCHER_INVALID_STATE", 409, "Voucher not DRAFT")
    if v["voucher_type"] == "PANEL_FEE":
        case = DB["cases"].get(v["case_id"])
        if not case or case["status"] != "DISPOSED":
            raise ApiError("ERR_CASE_NOT_DISPOSED", 409, "Case not DISPOSED")
    else:
        sr = DB["service_requests"].get(v["service_request_id"])
        if not sr or sr["status"] != "COMPLETED":
            raise ApiError("ERR_SERVICE_REQUEST_NOT_COMPLETED", 409,
                           "Service request not COMPLETED")
    v["status"] = "SUBMITTED"
    bump(v)
    return ok(serialize(v, "voucher"))


@app.route("/vouchers/<voucher_id>/approve", methods=["POST"])
def approve_voucher(voucher_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    v = must_get("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    if v["status"] != "SUBMITTED":
        raise ApiError("ERR_VOUCHER_INVALID_STATE", 409, "Voucher not SUBMITTED")
    case = DB["cases"].get(v["case_id"])
    if v["voucher_type"] == "PANEL_FEE":
        rate = DB["attorneys"][v["attorney_id"]]["hourly_rate_cents"]
        gross = round_half_up_int(to_dec(v["claimed_hours"]) * to_dec(rate))
        prior = sum(o["approved_amount_cents"] for o in DB["vouchers"].values()
                    if o["case_id"] == v["case_id"] and o["voucher_type"] == "PANEL_FEE"
                    and o["status"] == "APPROVED")
        remaining = max(0, CASE_FEE_CAP[case["charge_class"]] - prior)
        approved = min(gross, remaining)
    else:
        sr = DB["service_requests"][v["service_request_id"]]
        rate = sr["estimated_rate_cents"]
        gross = round_half_up_int(to_dec(v["claimed_hours"]) * to_dec(rate))
        prior = sum(o["approved_amount_cents"] for o in DB["vouchers"].values()
                    if o["service_request_id"] == v["service_request_id"]
                    and o["status"] == "APPROVED")
        remaining = max(0, sr["authorized_amount_cents"] - prior)
        approved = min(gross, remaining)
    v["approved_amount_cents"] = approved
    v["status"] = "APPROVED"
    bump(v)
    office = DB["offices"].get(case["office_id"]) if case else None
    if office:
        office["voucher_spent_cents"] += approved
        recompute_budget_status(office)
        bump(office)
    return ok(serialize(v, "voucher"))


@app.route("/vouchers/<voucher_id>/reject", methods=["POST"])
def reject_voucher(voucher_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    v = must_get("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    if v["status"] != "SUBMITTED":
        raise ApiError("ERR_VOUCHER_INVALID_STATE", 409, "Voucher not SUBMITTED")
    v["status"] = "REJECTED"
    bump(v)
    return ok(serialize(v, "voucher"))


@app.route("/vouchers/<voucher_id>/revise", methods=["POST"])
def revise_voucher(voucher_id):
    uid, role = require_auth()
    require_role(role, ["Attorney"])
    v = must_get("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    if v["attorney_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not the owning attorney")
    if v["status"] != "REJECTED":
        raise ApiError("ERR_VOUCHER_INVALID_STATE", 409, "Voucher not REJECTED")
    v["status"] = "DRAFT"
    v["approved_amount_cents"] = 0
    bump(v)
    return ok(serialize(v, "voucher"))


@app.route("/vouchers/<voucher_id>/void", methods=["POST"])
def void_voucher(voucher_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    v = must_get("vouchers", voucher_id, "ERR_VOUCHER_NOT_FOUND")
    if v["status"] != "APPROVED":
        raise ApiError("ERR_VOUCHER_INVALID_STATE", 409, "Voucher not APPROVED")
    approved = v["approved_amount_cents"]
    v["status"] = "VOIDED"
    bump(v)
    case = DB["cases"].get(v["case_id"])
    office = DB["offices"].get(case["office_id"]) if case else None
    if office:
        office["voucher_spent_cents"] -= approved
        recompute_budget_status(office)
        bump(office)
    return ok(serialize(v, "voucher"))


# ===========================================================================
# RecoupmentOrder
# ===========================================================================
@app.route("/recoupment-orders/<order_id>", methods=["GET"])
def get_recoupment_order(order_id):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    o = must_get("recoupment_orders", order_id, "ERR_RECOUPMENT_ORDER_NOT_FOUND")
    return ok(serialize(o, "recoupment_order"))


@app.route("/recoupment-orders", methods=["GET"])
def list_recoupment_orders():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    filters = {"case_id": request.args.get("case_id"),
               "status": request.args.get("status")}
    return list_response("recoupment_orders", "recoupment_order", filters)


@app.route("/recoupment-orders/<order_id>/collect", methods=["POST"])
def collect_recoupment(order_id):
    _, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    o = must_get("recoupment_orders", order_id, "ERR_RECOUPMENT_ORDER_NOT_FOUND")
    body = get_body()
    amount = req_int(body, "amount_cents", min_v=0, min_exclusive=True)
    if o["status"] not in ("ASSESSED", "PARTIALLY_COLLECTED"):
        raise ApiError("ERR_RECOUPMENT_NOT_COLLECTIBLE", 409, "Not collectible")
    o["collected_amount_cents"] += amount
    if o["collected_amount_cents"] >= o["assessed_amount_cents"]:
        o["status"] = "SATISFIED"
    else:
        o["status"] = "PARTIALLY_COLLECTED"
    bump(o)
    return ok(serialize(o, "recoupment_order"))


@app.route("/recoupment-orders/<order_id>/waive", methods=["POST"])
def waive_recoupment(order_id):
    uid, role = require_auth()
    require_role(role, ["SupervisingAttorney"])
    o = must_get("recoupment_orders", order_id, "ERR_RECOUPMENT_ORDER_NOT_FOUND")
    if o["status"] not in ("ASSESSED", "PARTIALLY_COLLECTED"):
        raise ApiError("ERR_RECOUPMENT_NOT_COLLECTIBLE", 409, "Not collectible")
    screening = decided_screening_for_case(o["case_id"])
    if screening and screening["decided_by_user_id"] is not None \
            and screening["decided_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Waiver must differ from screening decider")
    o["status"] = "WAIVED"
    o["waived_by_user_id"] = uid
    bump(o)
    return ok(serialize(o, "recoupment_order"))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    body = get_body()
    raw = body.get("to_iso8601")
    try:
        dt = parse_iso(raw)
    except (ValueError, TypeError):
        v_error("to_iso8601 must be a valid ISO 8601 datetime")
    LOGICAL_CLOCK[0] = dt
    return ok({})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
