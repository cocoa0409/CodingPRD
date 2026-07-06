"""Foundation Repair & Structural Stabilization API.

Single-file Flask implementation. In-memory store, logical clock, no seeding.
All structural names (headers, envelope fields, error ids, pagination params)
are taken verbatim from PRD.md / SCAFFOLD.yaml for task_0546_foundation_repair.
"""

import os
import uuid
import random
import string
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
PIER_TIER1_CENTS = 120000
PIER_TIER2_CENTS = 165000
PIER_TIER3_CENTS = 210000
ANCHOR_UNIT_CENTS = 45000
SOIL_MULT = {"STABLE": Decimal("1.00"), "EXPANSIVE": Decimal("1.15"), "UNSTABLE": Decimal("1.30")}
ACCESS_MULT = {"EASY": Decimal("1.00"), "MODERATE": Decimal("1.10"), "HARD": Decimal("1.25")}
PIER_TOLERANCE = 2

VOLUME_DISCOUNT_THRESHOLD_CENTS = 2000000
VOLUME_DISCOUNT_RATE = Decimal("0.05")
PLAN_FEE_RATE = {"CASH": Decimal("0.00"), "PLAN_12": Decimal("0.05"), "PLAN_60": Decimal("0.12")}
FINANCING_LIMIT_CENTS = 5000000

INCHES_PER_PIER = Decimal("0.5")
REMEDIATION_PIER_CENTS = 150000
MISSED_PENALTY = Decimal("0.10")
COVERAGE_FLOOR = Decimal("0.50")

QUOTE_VALID_DAYS = 30
VISIT_INTERVAL_DAYS = 365
MIN_VISIT_GAP_DAYS = 300

REGIONS = {"NORTH", "SOUTH", "EAST", "WEST"}
SOIL_CLASSES = {"STABLE", "EXPANSIVE", "UNSTABLE"}
ACCESS_LEVELS = {"EASY", "MODERATE", "HARD"}
FINANCING_PLANS = {"CASH", "PLAN_12", "PLAN_60"}
PERMIT_TYPES = {"STANDARD", "STRUCTURAL", "ENGINEERED"}
DECISIONS = {"APPROVE", "REJECT"}

RECOGNIZED_ROLES = {"SalesAgent", "FieldEngineer", "OpsCoordinator",
                    "ClaimsAdjuster", "Customer", "Admin"}
ALL_ROLES = RECOGNIZED_ROLES

# ---------------------------------------------------------------------------
# In-memory data store (fresh on every boot — NO seeding)
# ---------------------------------------------------------------------------
DB = {
    "leads": {},
    "inspections": {},
    "scopes": {},
    "quotes": {},
    "jobs": {},
    "crews": {},
    "permits": {},
    "warranties": {},
    "visits": {},
    "claims": {},
}
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}
_SEQ = {"n": 0}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err_unauth(m="Missing or unrecognized X-User-Role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, m)


def err_forbidden(m="Not permitted"):
    return ApiError("ERR_FORBIDDEN", 403, m)


def err_not_found(m="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, m)


def err_validation(m="Invalid request body"):
    return ApiError("ERR_VALIDATION", 422, m)


def err_stale(m="expected_lead_version does not match current Lead.version"):
    return ApiError("ERR_STALE_VERSION", 412, m)


def err_state(m="Illegal state transition"):
    return ApiError("ERR_INVALID_STATE", 409, m)


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def now_dt():
    return CLOCK["now"]


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_iso():
    return fmt_dt(now_dt())


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)  # may raise ValueError
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def gen_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def base_entity():
    ts = now_iso()
    return {
        "id": gen_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def round_half_up(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def depth_tier_unit(depth_ft):
    if depth_ft < 15:
        return PIER_TIER1_CENTS
    if depth_ft < 25:
        return PIER_TIER2_CENTS
    return PIER_TIER3_CENTS


def pier_pricing(scope, inspection, n_piers):
    tier = depth_tier_unit(scope["avg_pier_depth_ft"])
    soil = SOIL_MULT[inspection["soil_class"]]
    access = ACCESS_MULT[scope["access_difficulty"]]
    per_pier = round_half_up(Decimal(tier) * soil * access)
    pier_subtotal = per_pier * n_piers
    anchor_subtotal = scope["anchor_count"] * ANCHOR_UNIT_CENTS
    return pier_subtotal + anchor_subtotal


def financing_total(subtotal_cents, financing_plan):
    if subtotal_cents >= VOLUME_DISCOUNT_THRESHOLD_CENTS:
        discount = round_half_up(Decimal(subtotal_cents) * VOLUME_DISCOUNT_RATE)
    else:
        discount = 0
    financed = subtotal_cents - discount
    fee = round_half_up(Decimal(financed) * PLAN_FEE_RATE[financing_plan])
    total = financed + fee
    return financed, fee, total


def claim_settlement(reported_settlement_inches, missed_count):
    piers_needed = int(
        (Decimal(str(reported_settlement_inches)) / INCHES_PER_PIER).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    full_cost = piers_needed * REMEDIATION_PIER_CENTS
    coverage = Decimal(1) - MISSED_PENALTY * missed_count
    if coverage < COVERAGE_FLOOR:
        coverage = COVERAGE_FLOOR
    settlement = round_half_up(Decimal(full_cost) * coverage)
    variant = "FULL" if missed_count == 0 else "PRORATED"
    return settlement, variant


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    if role is None or role not in RECOGNIZED_ROLES:
        raise err_unauth()
    uid = request.headers.get("X-User-ID")
    return uid, role


def authorize(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise err_forbidden("Role %s may not perform this operation" % role)
    return uid, role


def require_customer_owns(role, uid, lead_id):
    if role == "Customer" and uid != lead_id:
        raise err_forbidden("Customer does not own this resource")


# ---------------------------------------------------------------------------
# Store lookup
# ---------------------------------------------------------------------------
def get_or_404(store, _id):
    ent = DB[store].get(_id)
    if ent is None:
        raise err_not_found("%s '%s' not found" % (store, _id))
    return ent


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")
    return body


def req_str(body, name):
    v = body.get(name)
    if v is None or not isinstance(v, str) or v == "":
        raise err_validation("Field '%s' must be a non-empty string" % name)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise err_validation("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed):
    if name not in body or body.get(name) is None:
        return None
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def req_int(body, name):
    v = body.get(name)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field '%s' must be an integer" % name)
    return v


def opt_bool(body, name, default=False):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, bool):
        raise err_validation("Field '%s' must be a boolean" % name)
    return v


def req_num(body, name):
    v = body.get(name)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation("Field '%s' must be a number" % name)
    return v


def req_datetime(body, name):
    v = body.get(name)
    if v is None or not isinstance(v, str):
        raise err_validation("Field '%s' must be an ISO 8601 datetime string" % name)
    try:
        parse_dt(v)
    except ValueError:
        raise err_validation("Field '%s' is not a valid datetime" % name)
    return v


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def effective_quote_status(q):
    if q["status"] == "SENT" and q.get("expires_at"):
        if now_dt() > parse_dt(q["expires_at"]):
            return "EXPIRED"
    return q["status"]


def serialize(entity, kind=None):
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    if kind == "quote":
        out["status"] = effective_quote_status(entity)
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}


def ok_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, kind):
    limit, offset = read_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    data = [serialize(e, kind) for e in page]
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": data}
    return jsonify(body), 200


def read_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(500)
def handle_500(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


@app.route("/", methods=["GET"])
def root():
    return ok_object({"service": "foundation-repair"}, 200)


# ===========================================================================
# LEAD
# ===========================================================================
@app.route("/foundation/leads", methods=["POST"])
def create_lead():
    authorize({"SalesAgent"})
    body = get_body()
    customer_name = req_str(body, "customer_name")
    property_address = req_str(body, "property_address")
    contact_email = req_str(body, "contact_email")
    region_code = req_enum(body, "region_code", REGIONS)
    lead = base_entity()
    lead.update({
        "customer_name": customer_name,
        "property_address": property_address,
        "contact_email": contact_email,
        "region_code": region_code,
        "financing_balance_cents": 0,
        "active_visit_count": 0,
    })
    DB["leads"][lead["id"]] = lead
    return ok_object(serialize(lead), 201)


@app.route("/foundation/leads/<lead_id>", methods=["GET"])
def get_lead(lead_id):
    authorize(ALL_ROLES)
    lead = get_or_404("leads", lead_id)
    return ok_object(serialize(lead), 200)


@app.route("/foundation/leads", methods=["GET"])
def list_leads():
    authorize(ALL_ROLES)
    region = request.args.get("region_code")
    items = [l for l in DB["leads"].values()
             if region is None or l["region_code"] == region]
    return ok_array(items, None)


# ===========================================================================
# INSPECTION
# ===========================================================================
@app.route("/foundation/inspections", methods=["POST"])
def create_inspection():
    authorize({"SalesAgent"})
    body = get_body()
    lead_id = body.get("lead_id")
    if lead_id is None:
        raise err_validation("Field 'lead_id' is required")
    get_or_404("leads", lead_id)
    scheduled_at = req_datetime(body, "scheduled_at")
    insp = base_entity()
    insp.update({
        "lead_id": lead_id,
        "scheduled_at": scheduled_at,
        "soil_class": None,
        "crack_severity": None,
        "max_crack_width_mm": None,
        "settlement_inches": None,
        "status": "SCHEDULED",
    })
    DB["inspections"][insp["id"]] = insp
    return ok_object(serialize(insp), 201)


@app.route("/foundation/inspections/<inspection_id>/complete", methods=["POST"])
def complete_inspection(inspection_id):
    authorize({"FieldEngineer"})
    insp = get_or_404("inspections", inspection_id)
    body = get_body()
    soil_class = req_enum(body, "soil_class", SOIL_CLASSES)
    crack_severity = req_int(body, "crack_severity")
    if crack_severity < 0 or crack_severity > 5:
        raise err_validation("crack_severity must be between 0 and 5")
    max_crack_width_mm = req_num(body, "max_crack_width_mm")
    settlement_inches = req_num(body, "settlement_inches")
    if insp["status"] != "SCHEDULED":
        raise err_state("Inspection is not SCHEDULED")
    insp.update({
        "soil_class": soil_class,
        "crack_severity": crack_severity,
        "max_crack_width_mm": max_crack_width_mm,
        "settlement_inches": settlement_inches,
        "status": "COMPLETED",
    })
    touch(insp)
    return ok_object(serialize(insp), 200)


@app.route("/foundation/inspections/<inspection_id>/cancel", methods=["POST"])
def cancel_inspection(inspection_id):
    authorize({"SalesAgent"})
    insp = get_or_404("inspections", inspection_id)
    if insp["status"] != "SCHEDULED":
        raise err_state("Inspection is not SCHEDULED")
    insp["status"] = "CANCELLED"
    touch(insp)
    return ok_object(serialize(insp), 200)


@app.route("/foundation/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    authorize(ALL_ROLES)
    insp = get_or_404("inspections", inspection_id)
    return ok_object(serialize(insp), 200)


@app.route("/foundation/inspections", methods=["GET"])
def list_inspections():
    authorize(ALL_ROLES)
    lead_id = request.args.get("lead_id")
    items = [i for i in DB["inspections"].values()
             if lead_id is None or i["lead_id"] == lead_id]
    return ok_array(items, None)


# ===========================================================================
# ENGINEERING SCOPE
# ===========================================================================
@app.route("/foundation/scopes", methods=["POST"])
def create_scope():
    authorize({"FieldEngineer"})
    body = get_body()
    lead_id = body.get("lead_id")
    inspection_id = body.get("inspection_id")
    if lead_id is None:
        raise err_validation("Field 'lead_id' is required")
    lead = get_or_404("leads", lead_id)
    if inspection_id is None:
        raise err_validation("Field 'inspection_id' is required")
    insp = get_or_404("inspections", inspection_id)
    # schema
    pier_count = req_int(body, "pier_count")
    anchor_count = req_int(body, "anchor_count")
    avg_pier_depth_ft = req_num(body, "avg_pier_depth_ft")
    access_difficulty = req_enum(body, "access_difficulty", ACCESS_LEVELS)
    supplemental = opt_bool(body, "supplemental_engineering", False)
    expected_lead_version = req_int(body, "expected_lead_version")
    # OCC (priority 5)
    if expected_lead_version != lead["version"]:
        raise err_stale()
    # state (priority 6)
    if insp["status"] != "COMPLETED":
        raise err_state("Referenced inspection is not COMPLETED")
    # side effects: supersede prior non-terminal scopes for the lead
    for s in DB["scopes"].values():
        if s["lead_id"] == lead_id and s["status"] in ("DRAFT", "ENGINEERED"):
            s["status"] = "SUPERSEDED"
            touch(s)
    scope = base_entity()
    scope.update({
        "lead_id": lead_id,
        "inspection_id": inspection_id,
        "pier_count": pier_count,
        "anchor_count": anchor_count,
        "avg_pier_depth_ft": avg_pier_depth_ft,
        "access_difficulty": access_difficulty,
        "supplemental_engineering": supplemental,
        "status": "DRAFT",
    })
    DB["scopes"][scope["id"]] = scope
    # increment lead version by 1
    touch(lead)
    return ok_object(serialize(scope), 201)


@app.route("/foundation/scopes/<scope_id>/finalize", methods=["POST"])
def finalize_scope(scope_id):
    authorize({"FieldEngineer"})
    scope = get_or_404("scopes", scope_id)
    if scope["status"] != "DRAFT":
        raise err_state("Scope is not DRAFT")
    if scope["pier_count"] < 1:
        raise ApiError("ERR_NO_PIERS", 422, "Scope finalize requires pier_count >= 1")
    scope["status"] = "ENGINEERED"
    touch(scope)
    return ok_object(serialize(scope), 200)


@app.route("/foundation/scopes/<scope_id>", methods=["GET"])
def get_scope(scope_id):
    authorize(ALL_ROLES)
    scope = get_or_404("scopes", scope_id)
    return ok_object(serialize(scope), 200)


@app.route("/foundation/scopes", methods=["GET"])
def list_scopes():
    authorize(ALL_ROLES)
    lead_id = request.args.get("lead_id")
    inspection_id = request.args.get("inspection_id")
    items = []
    for s in DB["scopes"].values():
        if lead_id is not None and s["lead_id"] != lead_id:
            continue
        if inspection_id is not None and s["inspection_id"] != inspection_id:
            continue
        items.append(s)
    return ok_array(items, None)


# ===========================================================================
# QUOTE
# ===========================================================================
@app.route("/foundation/quotes", methods=["POST"])
def create_quote():
    authorize({"SalesAgent"})
    body = get_body()
    lead_id = body.get("lead_id")
    scope_id = body.get("scope_id")
    if lead_id is None:
        raise err_validation("Field 'lead_id' is required")
    get_or_404("leads", lead_id)
    if scope_id is None:
        raise err_validation("Field 'scope_id' is required")
    get_or_404("scopes", scope_id)
    financing_plan = req_enum(body, "financing_plan", FINANCING_PLANS)
    quote = base_entity()
    quote.update({
        "lead_id": lead_id,
        "scope_id": scope_id,
        "financing_plan": financing_plan,
        "subtotal_cents": None,
        "financing_fee_cents": None,
        "total_cents": None,
        "expires_at": None,
        "status": "DRAFT",
    })
    DB["quotes"][quote["id"]] = quote
    return ok_object(serialize(quote, "quote"), 201)


def _compute_quote_pricing(quote):
    scope = DB["scopes"][quote["scope_id"]]
    inspection = DB["inspections"][scope["inspection_id"]]
    subtotal = pier_pricing(scope, inspection, scope["pier_count"])
    financed, fee, total = financing_total(subtotal, quote["financing_plan"])
    quote["subtotal_cents"] = subtotal
    quote["financing_fee_cents"] = fee
    quote["total_cents"] = total
    quote["expires_at"] = fmt_dt(now_dt() + timedelta(days=QUOTE_VALID_DAYS))


@app.route("/foundation/quotes/<quote_id>/send", methods=["POST"])
def send_quote(quote_id):
    authorize({"SalesAgent"})
    quote = get_or_404("quotes", quote_id)
    if quote["status"] not in ("DRAFT", "REVISED"):
        raise err_state("Quote cannot be sent from its current state")
    _compute_quote_pricing(quote)
    quote["status"] = "SENT"
    touch(quote)
    return ok_object(serialize(quote, "quote"), 200)


@app.route("/foundation/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id):
    uid, role = authorize({"Customer"})
    quote = get_or_404("quotes", quote_id)
    require_customer_owns(role, uid, quote["lead_id"])
    # state (6): must be SENT
    if quote["status"] != "SENT":
        raise err_state("Quote is not SENT")
    # quote expired (7)
    if now_dt() > parse_dt(quote["expires_at"]):
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "Quote has expired")
    # scope engineered (12)
    scope = DB["scopes"][quote["scope_id"]]
    if scope["status"] != "ENGINEERED":
        raise ApiError("ERR_SCOPE_NOT_ENGINEERED", 409,
                       "Quote's EngineeringScope is not ENGINEERED")
    # financing limit (21) on financed_principal
    financed, _fee, _total = financing_total(quote["subtotal_cents"], quote["financing_plan"])
    if financed > FINANCING_LIMIT_CENTS:
        raise ApiError("ERR_FINANCING_LIMIT_EXCEEDED", 402,
                       "financed principal exceeds FINANCING_LIMIT_CENTS")
    # transition + cascade
    quote["status"] = "ACCEPTED"
    touch(quote)
    lead = DB["leads"][quote["lead_id"]]
    job = base_entity()
    job.update({
        "lead_id": quote["lead_id"],
        "quote_id": quote["id"],
        "source_claim_id": None,
        "crew_id": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "piers_installed": None,
        "adjustment_inches": None,
        "final_subtotal_cents": None,
        "final_total_cents": None,
        "fulfillment_status": "UNSCHEDULED",
        "permit_status": "NOT_STARTED",
    })
    DB["jobs"][job["id"]] = job
    lead["financing_balance_cents"] += quote["total_cents"]
    touch(lead)  # single +1: financing balance update + version increment
    return ok_object(serialize(quote, "quote"), 200)


@app.route("/foundation/quotes/<quote_id>/reject", methods=["POST"])
def reject_quote(quote_id):
    uid, role = authorize({"Customer"})
    quote = get_or_404("quotes", quote_id)
    require_customer_owns(role, uid, quote["lead_id"])
    if effective_quote_status(quote) != "SENT":
        raise err_state("Quote is not SENT")
    quote["status"] = "REJECTED"
    touch(quote)
    return ok_object(serialize(quote, "quote"), 200)


@app.route("/foundation/quotes/<quote_id>/revise", methods=["POST"])
def revise_quote(quote_id):
    authorize({"SalesAgent"})
    quote = get_or_404("quotes", quote_id)
    body = get_body()
    new_plan = opt_enum(body, "financing_plan", FINANCING_PLANS)
    if effective_quote_status(quote) != "SENT":
        raise err_state("Quote is not SENT")
    if new_plan is not None:
        quote["financing_plan"] = new_plan
    quote["status"] = "REVISED"
    touch(quote)
    return ok_object(serialize(quote, "quote"), 200)


@app.route("/foundation/quotes/<quote_id>", methods=["GET"])
def get_quote(quote_id):
    authorize(ALL_ROLES)
    quote = get_or_404("quotes", quote_id)
    return ok_object(serialize(quote, "quote"), 200)


@app.route("/foundation/quotes", methods=["GET"])
def list_quotes():
    authorize(ALL_ROLES)
    lead_id = request.args.get("lead_id")
    scope_id = request.args.get("scope_id")
    items = []
    for q in DB["quotes"].values():
        if lead_id is not None and q["lead_id"] != lead_id:
            continue
        if scope_id is not None and q["scope_id"] != scope_id:
            continue
        items.append(q)
    return ok_array(items, "quote")


# ===========================================================================
# CREW
# ===========================================================================
@app.route("/foundation/crews", methods=["POST"])
def create_crew():
    authorize({"Admin"})
    body = get_body()
    crew_name = req_str(body, "crew_name")
    region_code = req_enum(body, "region_code", REGIONS)
    crew = base_entity()
    crew.update({
        "crew_name": crew_name,
        "region_code": region_code,
        "booked_minutes": 0,
    })
    DB["crews"][crew["id"]] = crew
    return ok_object(serialize(crew), 201)


@app.route("/foundation/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    authorize(ALL_ROLES)
    crew = get_or_404("crews", crew_id)
    return ok_object(serialize(crew), 200)


@app.route("/foundation/crews", methods=["GET"])
def list_crews():
    authorize(ALL_ROLES)
    region = request.args.get("region_code")
    items = [c for c in DB["crews"].values()
             if region is None or c["region_code"] == region]
    return ok_array(items, None)


# ===========================================================================
# PERMIT
# ===========================================================================
@app.route("/foundation/permits", methods=["POST"])
def create_permit():
    authorize({"OpsCoordinator"})
    body = get_body()
    job_id = body.get("job_id")
    if job_id is None:
        raise err_validation("Field 'job_id' is required")
    job = get_or_404("jobs", job_id)
    permit_type = req_enum(body, "permit_type", PERMIT_TYPES)
    if job["fulfillment_status"] == "CANCELLED":
        raise err_state("Cannot open a permit for a CANCELLED job")
    permit = base_entity()
    permit.update({
        "job_id": job_id,
        "permit_type": permit_type,
        "decision": None,
        "status": "PENDING",
    })
    DB["permits"][permit["id"]] = permit
    job["permit_status"] = "PENDING"
    touch(job)
    return ok_object(serialize(permit), 201)


@app.route("/foundation/permits/<permit_id>/decide", methods=["POST"])
def decide_permit(permit_id):
    authorize({"OpsCoordinator"})
    permit = get_or_404("permits", permit_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    if permit["status"] != "PENDING":
        raise err_state("Permit is not PENDING")
    permit["decision"] = decision
    new_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    permit["status"] = new_status
    touch(permit)
    job = DB["jobs"].get(permit["job_id"])
    if job is not None:
        job["permit_status"] = new_status
        touch(job)
    return ok_object(serialize(permit), 200)


@app.route("/foundation/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    authorize(ALL_ROLES)
    permit = get_or_404("permits", permit_id)
    return ok_object(serialize(permit), 200)


@app.route("/foundation/permits", methods=["GET"])
def list_permits():
    authorize(ALL_ROLES)
    job_id = request.args.get("job_id")
    items = [p for p in DB["permits"].values()
             if job_id is None or p["job_id"] == job_id]
    return ok_array(items, None)


# ===========================================================================
# JOB
# ===========================================================================
def _window_minutes(start_s, end_s):
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    return int((end - start).total_seconds() // 60)


@app.route("/foundation/jobs/<job_id>/schedule", methods=["POST"])
def schedule_job(job_id):
    authorize({"OpsCoordinator"})
    job = get_or_404("jobs", job_id)
    body = get_body()
    crew_id = body.get("crew_id")
    if crew_id is None:
        raise err_validation("Field 'crew_id' is required")
    crew = get_or_404("crews", crew_id)
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    # state (6)
    if job["fulfillment_status"] != "UNSCHEDULED":
        raise err_state("Job is not UNSCHEDULED")
    start_dt = parse_dt(scheduled_start)
    end_dt = parse_dt(scheduled_end)
    # unsafe soil (8) — only for quote-backed jobs (source inspection exists)
    if job.get("quote_id"):
        quote = DB["quotes"][job["quote_id"]]
        scope = DB["scopes"][quote["scope_id"]]
        inspection = DB["inspections"][scope["inspection_id"]]
        if inspection["soil_class"] == "UNSTABLE" and not scope["supplemental_engineering"]:
            raise ApiError("ERR_UNSAFE_SOIL_UNMITIGATED", 422,
                           "UNSTABLE soil requires supplemental_engineering")
    # crew double booked (9) — half-open overlap, adjacency allowed
    for other in DB["jobs"].values():
        if other["id"] == job["id"]:
            continue
        if other.get("crew_id") != crew_id:
            continue
        if other["fulfillment_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        o_start = parse_dt(other["scheduled_start"])
        o_end = parse_dt(other["scheduled_end"])
        if start_dt < o_end and o_start < end_dt:
            raise ApiError("ERR_CREW_DOUBLE_BOOKED", 409,
                           "Crew already booked for an overlapping window")
    # permit approved (11)
    if job["permit_status"] != "APPROVED":
        raise ApiError("ERR_PERMIT_NOT_APPROVED", 409, "Job permit_status is not APPROVED")
    # crew region mismatch (14)
    lead = DB["leads"][job["lead_id"]]
    if crew["region_code"] != lead["region_code"]:
        raise ApiError("ERR_CREW_REGION_MISMATCH", 409,
                       "Crew region does not match lead region")
    # schedule window invalid (17)
    if not (end_dt > start_dt):
        raise ApiError("ERR_SCHEDULE_WINDOW_INVALID", 422,
                       "scheduled_end must be strictly after scheduled_start")
    # commit
    job["crew_id"] = crew_id
    job["scheduled_start"] = scheduled_start
    job["scheduled_end"] = scheduled_end
    job["fulfillment_status"] = "SCHEDULED"
    touch(job)
    crew["booked_minutes"] += _window_minutes(scheduled_start, scheduled_end)
    touch(crew)
    return ok_object(serialize(job), 200)


@app.route("/foundation/jobs/<job_id>/start", methods=["POST"])
def start_job(job_id):
    authorize({"OpsCoordinator"})
    job = get_or_404("jobs", job_id)
    if job["fulfillment_status"] != "SCHEDULED":
        raise err_state("Job is not SCHEDULED")
    job["fulfillment_status"] = "IN_PROGRESS"
    touch(job)
    return ok_object(serialize(job), 200)


@app.route("/foundation/jobs/<job_id>/complete", methods=["POST"])
def complete_job(job_id):
    authorize({"OpsCoordinator"})
    job = get_or_404("jobs", job_id)
    body = get_body()
    piers_installed = req_int(body, "piers_installed")
    adjustment_inches = req_num(body, "adjustment_inches")
    if job["fulfillment_status"] != "IN_PROGRESS":
        raise err_state("Job is not IN_PROGRESS")
    is_install = job.get("quote_id") is not None
    if is_install:
        quote = DB["quotes"][job["quote_id"]]
        scope = DB["scopes"][quote["scope_id"]]
        if abs(piers_installed - scope["pier_count"]) > PIER_TOLERANCE:
            raise ApiError("ERR_PIER_COUNT_MISMATCH", 422,
                           "piers_installed deviates beyond PIER_TOLERANCE")
    job["piers_installed"] = piers_installed
    job["adjustment_inches"] = adjustment_inches
    job["fulfillment_status"] = "COMPLETED"
    if is_install:
        inspection = DB["inspections"][scope["inspection_id"]]
        final_subtotal = pier_pricing(scope, inspection, piers_installed)
        _financed, _fee, final_total = financing_total(final_subtotal, quote["financing_plan"])
        job["final_subtotal_cents"] = final_subtotal
        job["final_total_cents"] = final_total
    touch(job)
    if is_install:
        lead = DB["leads"][job["lead_id"]]
        activated_at = now_iso()
        warranty = base_entity()
        warranty.update({
            "lead_id": job["lead_id"],
            "job_id": job["id"],
            "holder_name": lead["customer_name"],
            "activated_at": activated_at,
            "transfer_count": 0,
            "remediation_count": 0,
            "covered_pier_count": piers_installed,
            "status": "ACTIVE",
        })
        DB["warranties"][warranty["id"]] = warranty
        # cascade hop 2: first maintenance visit
        visit = base_entity()
        visit.update({
            "warranty_id": warranty["id"],
            "crew_id": None,
            "scheduled_date": fmt_dt(parse_dt(activated_at) + timedelta(days=VISIT_INTERVAL_DAYS)),
            "tightening_turns": None,
            "status": "SCHEDULED",
        })
        DB["visits"][visit["id"]] = visit
        # cascade hop 3: lead active_visit_count += 1
        lead["active_visit_count"] += 1
        touch(lead)
    return ok_object(serialize(job), 200)


@app.route("/foundation/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    authorize({"OpsCoordinator"})
    job = get_or_404("jobs", job_id)
    prev = job["fulfillment_status"]
    if prev not in ("UNSCHEDULED", "SCHEDULED"):
        raise err_state("Job cannot be cancelled from its current state")
    job["fulfillment_status"] = "CANCELLED"
    touch(job)
    if prev == "SCHEDULED":
        crew = DB["crews"].get(job.get("crew_id"))
        if crew is not None:
            crew["booked_minutes"] -= _window_minutes(job["scheduled_start"], job["scheduled_end"])
            touch(crew)
    if job.get("quote_id"):
        quote = DB["quotes"][job["quote_id"]]
        lead = DB["leads"][job["lead_id"]]
        lead["financing_balance_cents"] -= quote["total_cents"]
        touch(lead)
    return ok_object(serialize(job), 200)


@app.route("/foundation/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    authorize(ALL_ROLES)
    job = get_or_404("jobs", job_id)
    return ok_object(serialize(job), 200)


@app.route("/foundation/jobs", methods=["GET"])
def list_jobs():
    authorize(ALL_ROLES)
    lead_id = request.args.get("lead_id")
    quote_id = request.args.get("quote_id")
    crew_id = request.args.get("crew_id")
    source_claim_id = request.args.get("source_claim_id")
    items = []
    for j in DB["jobs"].values():
        if lead_id is not None and j["lead_id"] != lead_id:
            continue
        if quote_id is not None and j.get("quote_id") != quote_id:
            continue
        if crew_id is not None and j.get("crew_id") != crew_id:
            continue
        if source_claim_id is not None and j.get("source_claim_id") != source_claim_id:
            continue
        items.append(j)
    return ok_array(items, None)


# ===========================================================================
# WARRANTY
# ===========================================================================
@app.route("/foundation/warranties/<warranty_id>/transfer", methods=["POST"])
def transfer_warranty(warranty_id):
    uid, role = authorize({"Customer"})
    warranty = get_or_404("warranties", warranty_id)
    require_customer_owns(role, uid, warranty["lead_id"])
    body = get_body()
    new_holder_name = req_str(body, "new_holder_name")
    if warranty["status"] != "ACTIVE":
        raise err_state("Warranty is not ACTIVE")
    warranty["holder_name"] = new_holder_name
    warranty["transfer_count"] += 1
    touch(warranty)
    return ok_object(serialize(warranty), 200)


@app.route("/foundation/warranties/<warranty_id>/void", methods=["POST"])
def void_warranty(warranty_id):
    authorize({"Admin"})
    warranty = get_or_404("warranties", warranty_id)
    if warranty["status"] != "ACTIVE":
        raise err_state("Warranty is not ACTIVE")
    warranty["status"] = "VOID"
    touch(warranty)
    return ok_object(serialize(warranty), 200)


@app.route("/foundation/warranties/<warranty_id>", methods=["GET"])
def get_warranty(warranty_id):
    authorize(ALL_ROLES)
    warranty = get_or_404("warranties", warranty_id)
    return ok_object(serialize(warranty), 200)


@app.route("/foundation/warranties", methods=["GET"])
def list_warranties():
    authorize(ALL_ROLES)
    lead_id = request.args.get("lead_id")
    job_id = request.args.get("job_id")
    items = []
    for w in DB["warranties"].values():
        if lead_id is not None and w["lead_id"] != lead_id:
            continue
        if job_id is not None and w["job_id"] != job_id:
            continue
        items.append(w)
    return ok_array(items, None)


# ===========================================================================
# MAINTENANCE VISIT
# ===========================================================================
@app.route("/foundation/maintenance-visits", methods=["POST"])
def create_visit():
    authorize({"OpsCoordinator"})
    body = get_body()
    warranty_id = body.get("warranty_id")
    if warranty_id is None:
        raise err_validation("Field 'warranty_id' is required")
    warranty = get_or_404("warranties", warranty_id)
    crew_id = body.get("crew_id")
    if crew_id is not None:
        get_or_404("crews", crew_id)
    scheduled_date = req_datetime(body, "scheduled_date")
    new_dt = parse_dt(scheduled_date)
    # Business checks in PRD §2.10 canonical order:
    #   visit-too-soon (10) < warranty-not-active (13) < visit-date-in-past (18)
    for v in DB["visits"].values():
        if v["warranty_id"] != warranty_id:
            continue
        existing = parse_dt(v["scheduled_date"])
        if abs((new_dt - existing).total_seconds()) < MIN_VISIT_GAP_DAYS * 86400:
            raise ApiError("ERR_VISIT_TOO_SOON", 409,
                           "Visit too close to an existing visit on the warranty")
    if warranty["status"] != "ACTIVE":
        raise ApiError("ERR_WARRANTY_NOT_ACTIVE", 409, "Warranty is not ACTIVE")
    if not (new_dt > now_dt()):
        raise ApiError("ERR_VISIT_DATE_IN_PAST", 422,
                       "scheduled_date must be in the future")
    visit = base_entity()
    visit.update({
        "warranty_id": warranty_id,
        "crew_id": crew_id,
        "scheduled_date": scheduled_date,
        "tightening_turns": None,
        "status": "SCHEDULED",
    })
    DB["visits"][visit["id"]] = visit
    lead = DB["leads"][warranty["lead_id"]]
    lead["active_visit_count"] += 1
    touch(lead)
    return ok_object(serialize(visit), 201)


@app.route("/foundation/maintenance-visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    authorize({"OpsCoordinator"})
    visit = get_or_404("visits", visit_id)
    body = get_body()
    tightening_turns = req_int(body, "tightening_turns")
    if visit["status"] != "SCHEDULED":
        raise err_state("Visit is not SCHEDULED")
    visit["tightening_turns"] = tightening_turns
    visit["status"] = "COMPLETED"
    touch(visit)
    _decrement_active_visit(visit)
    return ok_object(serialize(visit), 200)


@app.route("/foundation/maintenance-visits/<visit_id>/mark-missed", methods=["POST"])
def mark_missed_visit(visit_id):
    authorize({"OpsCoordinator"})
    visit = get_or_404("visits", visit_id)
    if visit["status"] != "SCHEDULED":
        raise err_state("Visit is not SCHEDULED")
    if not (now_dt() > parse_dt(visit["scheduled_date"])):
        raise ApiError("ERR_VISIT_NOT_DUE", 409, "Visit is not yet due")
    visit["status"] = "MISSED"
    touch(visit)
    _decrement_active_visit(visit)
    return ok_object(serialize(visit), 200)


def _decrement_active_visit(visit):
    warranty = DB["warranties"].get(visit["warranty_id"])
    if warranty is None:
        return
    lead = DB["leads"].get(warranty["lead_id"])
    if lead is None:
        return
    lead["active_visit_count"] -= 1
    touch(lead)


@app.route("/foundation/maintenance-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    authorize(ALL_ROLES)
    visit = get_or_404("visits", visit_id)
    return ok_object(serialize(visit), 200)


@app.route("/foundation/maintenance-visits", methods=["GET"])
def list_visits():
    authorize(ALL_ROLES)
    warranty_id = request.args.get("warranty_id")
    crew_id = request.args.get("crew_id")
    items = []
    for v in DB["visits"].values():
        if warranty_id is not None and v["warranty_id"] != warranty_id:
            continue
        if crew_id is not None and v.get("crew_id") != crew_id:
            continue
        items.append(v)
    return ok_array(items, None)


# ===========================================================================
# CLAIM
# ===========================================================================
@app.route("/foundation/claims", methods=["POST"])
def create_claim():
    uid, role = authorize({"Customer"})
    body = get_body()
    warranty_id = body.get("warranty_id")
    if warranty_id is None:
        raise err_validation("Field 'warranty_id' is required")
    warranty = get_or_404("warranties", warranty_id)
    require_customer_owns(role, uid, warranty["lead_id"])
    description = req_str(body, "description")
    reported_settlement_inches = req_num(body, "reported_settlement_inches")
    if warranty["status"] != "ACTIVE":
        raise ApiError("ERR_WARRANTY_NOT_ACTIVE", 409, "Warranty is not ACTIVE")
    claim = base_entity()
    claim.update({
        "warranty_id": warranty_id,
        "description": description,
        "reported_settlement_inches": reported_settlement_inches,
        "settlement_cents": None,
        "coverage_variant": None,
        "remediation_job_id": None,
        "status": "FILED",
    })
    DB["claims"][claim["id"]] = claim
    return ok_object(serialize(claim), 201)


@app.route("/foundation/claims/<claim_id>/review", methods=["POST"])
def review_claim(claim_id):
    authorize({"ClaimsAdjuster"})
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "FILED":
        raise err_state("Claim is not FILED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims/<claim_id>/request-info", methods=["POST"])
def request_info_claim(claim_id):
    authorize({"ClaimsAdjuster"})
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise err_state("Claim is not UNDER_REVIEW")
    claim["status"] = "NEEDS_INFO"
    touch(claim)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims/<claim_id>/resubmit", methods=["POST"])
def resubmit_claim(claim_id):
    uid, role = authorize({"Customer"})
    claim = get_or_404("claims", claim_id)
    warranty = DB["warranties"][claim["warranty_id"]]
    require_customer_owns(role, uid, warranty["lead_id"])
    if claim["status"] != "NEEDS_INFO":
        raise err_state("Claim is not NEEDS_INFO")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    authorize({"ClaimsAdjuster"})
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise err_state("Claim is not UNDER_REVIEW")
    warranty = DB["warranties"][claim["warranty_id"]]
    missed = sum(1 for v in DB["visits"].values()
                 if v["warranty_id"] == warranty["id"] and v["status"] == "MISSED")
    settlement, variant = claim_settlement(claim["reported_settlement_inches"], missed)
    claim["settlement_cents"] = settlement
    claim["coverage_variant"] = variant
    claim["status"] = "APPROVED"
    # cascade hop 1: remediation job
    job = base_entity()
    job.update({
        "lead_id": warranty["lead_id"],
        "quote_id": None,
        "source_claim_id": claim["id"],
        "crew_id": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "piers_installed": None,
        "adjustment_inches": None,
        "final_subtotal_cents": None,
        "final_total_cents": None,
        "fulfillment_status": "UNSCHEDULED",
        "permit_status": "NOT_STARTED",
    })
    DB["jobs"][job["id"]] = job
    claim["remediation_job_id"] = job["id"]
    touch(claim)
    # cascade hop 2: warranty remediation_count += 1
    warranty["remediation_count"] += 1
    touch(warranty)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    authorize({"ClaimsAdjuster"})
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise err_state("Claim is not UNDER_REVIEW")
    claim["status"] = "DENIED"
    touch(claim)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims/<claim_id>/resolve", methods=["POST"])
def resolve_claim(claim_id):
    authorize({"ClaimsAdjuster"})
    claim = get_or_404("claims", claim_id)
    if claim["status"] != "APPROVED":
        raise err_state("Claim is not APPROVED")
    job = DB["jobs"].get(claim["remediation_job_id"])
    if job is None or job["fulfillment_status"] != "COMPLETED":
        raise ApiError("ERR_REMEDIATION_NOT_COMPLETE", 409,
                       "Remediation job is not COMPLETED")
    claim["status"] = "RESOLVED"
    touch(claim)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    authorize(ALL_ROLES)
    claim = get_or_404("claims", claim_id)
    return ok_object(serialize(claim), 200)


@app.route("/foundation/claims", methods=["GET"])
def list_claims():
    authorize(ALL_ROLES)
    warranty_id = request.args.get("warranty_id")
    remediation_job_id = request.args.get("remediation_job_id")
    items = []
    for c in DB["claims"].values():
        if warranty_id is not None and c["warranty_id"] != warranty_id:
            continue
        if remediation_job_id is not None and c.get("remediation_job_id") != remediation_job_id:
            continue
        items.append(c)
    return ok_array(items, None)


# ===========================================================================
# LOGICAL CLOCK (test driving)
# ===========================================================================
@app.route("/foundation/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize({"Admin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    if to_iso is None or not isinstance(to_iso, str):
        raise err_validation("Field 'to_iso8601' is required")
    try:
        new_dt = parse_dt(to_iso)
    except ValueError:
        raise err_validation("Field 'to_iso8601' is not a valid datetime")
    CLOCK["now"] = new_dt
    return ok_object({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
