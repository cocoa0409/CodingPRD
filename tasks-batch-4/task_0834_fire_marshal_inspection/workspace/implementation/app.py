"""Fire Marshal Plan Review & Fire Inspection API.

Python + Flask, in-memory only. Every behavior traces to a PRD sentence.
State is wiped on every process boot (the harness re-launches start.sh per test).
"""
import os
import re
import uuid
import random
import string
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD §3)
# ---------------------------------------------------------------------------
ROLES = {"Applicant", "PlanReviewer", "Inspector", "FireMarshal"}

OCCUPANCY_CLASSES = {"ASSEMBLY", "BUSINESS", "EDUCATIONAL", "FACTORY", "HIGH_HAZARD",
                     "INSTITUTIONAL", "MERCANTILE", "RESIDENTIAL", "STORAGE", "UTILITY"}
CONSTRUCTION_TYPES = {"TYPE_I", "TYPE_II", "TYPE_III", "TYPE_IV", "TYPE_V"}
PERMIT_TYPES = {"CONSTRUCTION", "TENANT_IMPROVEMENT", "HAZMAT", "TANK"}
INSPECTION_TYPES = {"PERIODIC", "COMPLAINT", "RE_INSPECTION", "FINAL"}
RESULTS = {"PASSED", "FAILED"}
SEVERITIES = {"MINOR", "MAJOR", "IMMINENT_HAZARD"}
DISCIPLINES = {"SPRINKLER", "ALARM", "EGRESS"}
DECISIONS = {"APPROVED", "CORRECTIONS_REQUIRED"}

BASE_PERMIT_FEE_CENTS = {"CONSTRUCTION": 20000, "TENANT_IMPROVEMENT": 10000,
                         "HAZMAT": 30000, "TANK": 25000}
VALUATION_RATE = Decimal("0.005")
STATE_SURCHARGE_RATE = Decimal("0.001")
TECH_FEE_RATE = Decimal("0.0004")
RESUBMIT_SURCHARGE_CENTS = 5000

OCCUPANT_LOAD_FACTOR = {"ASSEMBLY": 7, "BUSINESS": 150, "EDUCATIONAL": 20, "FACTORY": 100,
                        "HIGH_HAZARD": 100, "INSTITUTIONAL": 240, "MERCANTILE": 60,
                        "RESIDENTIAL": 200, "STORAGE": 500, "UTILITY": 300}
NET_AREA_RATIO = Decimal("0.85")

FLOW_COEFF = Decimal("0.09")
CONSTRUCTION_FACTOR = {"TYPE_I": Decimal("0.8"), "TYPE_II": Decimal("0.8"),
                       "TYPE_III": Decimal("1.0"), "TYPE_IV": Decimal("1.0"),
                       "TYPE_V": Decimal("1.5")}
OCCUPANCY_HAZARD_MULT = {"HIGH_HAZARD": Decimal("1.5"), "STORAGE": Decimal("1.25"),
                         "FACTORY": Decimal("1.25"), "ASSEMBLY": Decimal("1.0"),
                         "INSTITUTIONAL": Decimal("1.0"), "EDUCATIONAL": Decimal("1.0"),
                         "BUSINESS": Decimal("0.75"), "MERCANTILE": Decimal("0.75"),
                         "RESIDENTIAL": Decimal("0.75"), "UTILITY": Decimal("0.75")}
FLOW_MIN_GPM = 500
FLOW_MAX_GPM = 8000
FLOW_STEP = 250

HW_EXPONENT = 0.54
RESIDUAL_TARGET_PSI = 20

ABATEMENT_GRACE_DAYS = {"IMMINENT_HAZARD": 3, "MAJOR": 30, "MINOR": 90}

INSPECTION_BUFFER_DAYS = 14
FLOW_TEST_WINDOW_DAYS = 365
PERMIT_EXPIRY_DAYS = 365

CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401, "ERR_UNAUTHORIZED": 403, "ERR_NOT_OWNER": 403,
    "ERR_PROPERTY_NOT_FOUND": 404, "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_PLAN_REVIEW_NOT_FOUND": 404, "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404, "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_ABATEMENT_ORDER_NOT_FOUND": 404, "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_HYDRANT_NOT_FOUND": 404, "ERR_FLOW_TEST_NOT_FOUND": 404,
    "ERR_VALIDATION": 400, "ERR_INVALID_ENUM": 422, "ERR_MISSING_CONDITIONAL_FIELD": 422,
    "ERR_INVALID_STATE": 409, "ERR_APPLICATION_NOT_APPROVED": 409,
    "ERR_REVIEW_INCOMPLETE": 409, "ERR_OPEN_VIOLATIONS": 409,
    "ERR_FLOW_TEST_WINDOW_OVERLAP": 409, "ERR_INSPECTION_TOO_CLOSE": 409,
    "ERR_INVALID_FLOW_READINGS": 422, "ERR_INSUFFICIENT_FIRE_FLOW": 409,
    "ERR_FEE_UNPAID": 402, "ERR_STALE_VERSION": 412,
}


# ---------------------------------------------------------------------------
# In-memory store (wiped each boot) + logical clock
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.properties = {}
        self.permit_applications = {}
        self.plan_reviews = {}
        self.permits = {}
        self.inspections = {}
        self.violations = {}
        self.abatement_orders = {}
        self.certificates = {}
        self.hydrants = {}
        self.flow_tests = {}
        self.seq = 0
        self.permit_seq = 0
        self.clock = parse_dt(CLOCK_STARTUP_DEFAULT)


db = None  # initialized after helpers are defined


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


def to_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return to_iso(datetime.now(timezone.utc))


def clock_now():
    return db.clock


def clock_now_iso():
    return to_iso(db.clock)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").title()


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http


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


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": f"Internal error: {e}"}}
    return jsonify(body), 400


# ---------------------------------------------------------------------------
# Entity creation / mutation
# ---------------------------------------------------------------------------
def new_entity(fields):
    db.seq += 1
    now = wall_now_iso()
    ent = {
        "id": str(uuid.uuid4()),
        **fields,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.seq,
    }
    return ent


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = wall_now_iso()


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(allowed):
    if g.role not in allowed:
        err("ERR_UNAUTHORIZED", f"Role {g.role} may not perform this operation")


def body_json():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_str(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", f"Field {field} must be a non-empty string")
    return v


def require_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", f"Field {field} must be >= {minimum}")
    return v


def require_number(body, field):
    if field not in body or body[field] is None:
        err("ERR_VALIDATION", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", f"Field {field} must be a number")
    return v


def require_enum(value, allowed, field):
    if value not in allowed:
        err("ERR_INVALID_ENUM", f"Field {field} has an invalid value: {value}")
    return value


# ---------------------------------------------------------------------------
# Lookups (existence -> 404)
# ---------------------------------------------------------------------------
def find(coll, ident, error_id):
    ent = coll.get(ident)
    if ent is None:
        err(error_id, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Calculations (PRD §3)
# ---------------------------------------------------------------------------
def rhu_cents(product):
    return int(Decimal(product).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_permit_fee(permit_type, valuation_cents, resubmit_count):
    base = BASE_PERMIT_FEE_CENTS[permit_type]
    val = Decimal(valuation_cents)
    c1 = rhu_cents(val * VALUATION_RATE)
    c2 = rhu_cents(val * STATE_SURCHARGE_RATE)
    c3 = rhu_cents(val * TECH_FEE_RATE)
    surcharge = RESUBMIT_SURCHARGE_CENTS * resubmit_count
    return base + c1 + c2 + c3 + surcharge


def compute_property_metrics(prop):
    area = prop["total_floor_area_sqft"]
    occ = prop["occupancy_classification"]
    ctype = prop["construction_type"]
    factor = OCCUPANT_LOAD_FACTOR[occ]
    # occupant_load: floor(area * 0.85 / factor) via exact integer arithmetic
    occupant_load = (area * 85) // (100 * factor)
    design_occupant_load = area // factor
    prop["occupant_load"] = occupant_load
    prop["design_occupant_load"] = design_occupant_load
    # required exits step function (inclusive at lower edge)
    if occupant_load >= 1000:
        prop["required_exits"] = 4
    elif occupant_load >= 500:
        prop["required_exits"] = 3
    elif occupant_load >= 50:
        prop["required_exits"] = 2
    else:
        prop["required_exits"] = 1
    # required fire flow
    raw = Decimal(area) * FLOW_COEFF * CONSTRUCTION_FACTOR[ctype] * OCCUPANCY_HAZARD_MULT[occ]
    clamped = max(Decimal(FLOW_MIN_GPM), min(raw, Decimal(FLOW_MAX_GPM)))
    steps = (clamped / Decimal(FLOW_STEP)).quantize(Decimal("1"), rounding=ROUND_CEILING)
    prop["required_fire_flow_gpm"] = int(steps) * FLOW_STEP


def compute_available_flow(static_psi, residual_psi, measured_flow_gpm):
    ratio = (static_psi - RESIDUAL_TARGET_PSI) / (static_psi - residual_psi)
    value = measured_flow_gpm * (ratio ** HW_EXPONENT)
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    # items sorted by insertion order (created_at ascending)
    items = sorted(items, key=lambda e: e["_seq"])
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
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
    has_more = offset + len(page) < total
    meta_extra = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return [public(x) for x in page], meta_extra


def list_response(items):
    data, meta_extra = paginate(items)
    return ok(data, 200, "array", meta_extra)


# ---------------------------------------------------------------------------
# Cross-entity helpers
# ---------------------------------------------------------------------------
def violations_for_property(property_id):
    result = []
    for v in db.violations.values():
        insp = db.inspections.get(v["inspection_id"])
        if insp and insp["property_id"] == property_id:
            result.append(v)
    return result


def property_has_blocking_violation(property_id):
    for v in violations_for_property(property_id):
        if v["status"] in ("OPEN", "ESCALATED"):
            return True
    return False


def certificates_for_property(property_id):
    return [c for c in db.certificates.values() if c["property_id"] == property_id]


def suspend_certificates(property_id):
    """Cascade C1/C2: occupancy_status := SUSPENDED (unless already REVOKED),
    placard_status := RED."""
    for cert in certificates_for_property(property_id):
        if cert["occupancy_status"] != "REVOKED":
            cert["occupancy_status"] = "SUSPENDED"
        cert["placard_status"] = "RED"
        touch(cert)


# ---------------------------------------------------------------------------
# Property endpoints
# ---------------------------------------------------------------------------
@app.route("/api/properties", methods=["POST"])
def create_property():
    auth()
    require_role({"Applicant", "FireMarshal"})
    body = body_json()
    address = require_str(body, "address")
    owner_name = require_str(body, "owner_name")
    if "occupancy_classification" not in body or body["occupancy_classification"] is None:
        err("ERR_VALIDATION", "Missing required field: occupancy_classification")
    if "construction_type" not in body or body["construction_type"] is None:
        err("ERR_VALIDATION", "Missing required field: construction_type")
    area = require_int(body, "total_floor_area_sqft", minimum=1)
    stories = require_int(body, "stories", minimum=1)
    occ = require_enum(body["occupancy_classification"], OCCUPANCY_CLASSES, "occupancy_classification")
    ctype = require_enum(body["construction_type"], CONSTRUCTION_TYPES, "construction_type")
    prop = new_entity({
        "address": address, "owner_name": owner_name,
        "occupancy_classification": occ, "construction_type": ctype,
        "total_floor_area_sqft": area, "stories": stories,
        "occupant_load": 0, "design_occupant_load": 0,
        "required_exits": 0, "required_fire_flow_gpm": 0,
        "open_violation_count": 0, "fees_paid_cents": 0,
    })
    compute_property_metrics(prop)
    db.properties[prop["id"]] = prop
    return ok(public(prop), 201)


@app.route("/api/properties/<pid>", methods=["GET"])
def get_property(pid):
    auth()
    require_role(ROLES)
    prop = find(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
    return ok(public(prop))


@app.route("/api/properties/<pid>", methods=["PATCH"])
def update_property(pid):
    auth()
    require_role({"Applicant", "FireMarshal"})
    prop = find(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
    body = body_json()
    # Well-formedness of provided fields
    if "total_floor_area_sqft" in body and body["total_floor_area_sqft"] is not None:
        area = body["total_floor_area_sqft"]
        if isinstance(area, bool) or not isinstance(area, int) or area < 1:
            err("ERR_VALIDATION", "total_floor_area_sqft must be a positive integer")
    if "stories" in body and body["stories"] is not None:
        st = body["stories"]
        if isinstance(st, bool) or not isinstance(st, int) or st < 1:
            err("ERR_VALIDATION", "stories must be an integer >= 1")
    # Enum membership of provided enums
    if "occupancy_classification" in body and body["occupancy_classification"] is not None:
        require_enum(body["occupancy_classification"], OCCUPANCY_CLASSES, "occupancy_classification")
    if "construction_type" in body and body["construction_type"] is not None:
        require_enum(body["construction_type"], CONSTRUCTION_TYPES, "construction_type")
    for f in ("total_floor_area_sqft", "occupancy_classification", "construction_type", "stories"):
        if f in body and body[f] is not None:
            prop[f] = body[f]
    compute_property_metrics(prop)
    touch(prop)
    return ok(public(prop))


# ---------------------------------------------------------------------------
# PermitApplication endpoints
# ---------------------------------------------------------------------------
@app.route("/api/permit-applications", methods=["POST"])
def create_permit_application():
    auth()
    require_role({"Applicant"})
    body = body_json()
    # existence of provided FKs first (precedence 3)
    if body.get("property_id"):
        find(db.properties, body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    if body.get("flow_test_id"):
        find(db.flow_tests, body["flow_test_id"], "ERR_FLOW_TEST_NOT_FOUND")
    property_id = require_str(body, "property_id")
    applicant_user_id = require_str(body, "applicant_user_id")
    if "permit_type" not in body or body["permit_type"] is None:
        err("ERR_VALIDATION", "Missing required field: permit_type")
    valuation = require_int(body, "project_valuation_cents", minimum=0)
    scope_area = require_int(body, "scope_area_sqft", minimum=1)
    permit_type = require_enum(body["permit_type"], PERMIT_TYPES, "permit_type")
    flow_test_id = body.get("flow_test_id")
    app_ent = new_entity({
        "property_id": property_id, "applicant_user_id": applicant_user_id,
        "permit_type": permit_type, "project_valuation_cents": valuation,
        "scope_area_sqft": scope_area, "flow_test_id": flow_test_id,
        "status": "DRAFT", "estimated_fee_cents": None, "final_fee_cents": None,
        "amount_paid_cents": 0, "refunded_cents": 0, "resubmit_count": 0,
    })
    db.permit_applications[app_ent["id"]] = app_ent
    return ok(public(app_ent), 201)


@app.route("/api/permit-applications/<aid>", methods=["GET"])
def get_permit_application(aid):
    auth()
    require_role(ROLES)
    app_ent = find(db.permit_applications, aid, "ERR_APPLICATION_NOT_FOUND")
    return ok(public(app_ent))


@app.route("/api/permit-applications", methods=["GET"])
def list_permit_applications():
    auth()
    require_role(ROLES)
    items = list(db.permit_applications.values())
    pid = request.args.get("property_id")
    ftid = request.args.get("flow_test_id")
    status = request.args.get("status")
    if pid:
        items = [a for a in items if a["property_id"] == pid]
    if ftid:
        items = [a for a in items if a["flow_test_id"] == ftid]
    if status:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@app.route("/api/permit-applications/<aid>/submit", methods=["POST"])
def submit_permit_application(aid):
    auth()
    require_role({"Applicant"})
    app_ent = find(db.permit_applications, aid, "ERR_APPLICATION_NOT_FOUND")
    # ownership (precedence 4)
    if g.user_id != app_ent["applicant_user_id"]:
        err("ERR_NOT_OWNER", "Caller is not the owning applicant")
    # conditional field (precedence 7)
    if app_ent["permit_type"] in ("HAZMAT", "TANK") and not app_ent.get("flow_test_id"):
        err("ERR_MISSING_CONDITIONAL_FIELD", "flow_test_id required for HAZMAT/TANK submit")
    # state (precedence 8)
    if app_ent["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Application is not in DRAFT")
    # business: sufficient fire flow (precedence 15)
    if app_ent["permit_type"] in ("HAZMAT", "TANK"):
        ft = db.flow_tests.get(app_ent["flow_test_id"])
        prop = db.properties.get(app_ent["property_id"])
        if ft is None:
            err("ERR_FLOW_TEST_NOT_FOUND", "Referenced flow test not found")
        if ft["available_flow_at_20psi"] < prop["required_fire_flow_gpm"]:
            err("ERR_INSUFFICIENT_FIRE_FLOW", "Flow test available flow below required fire flow")
    # side effects: freeze estimated fee, open plan review, advance status
    app_ent["estimated_fee_cents"] = compute_permit_fee(
        app_ent["permit_type"], app_ent["project_valuation_cents"], 0)
    app_ent["status"] = "UNDER_REVIEW"
    touch(app_ent)
    review = new_entity({
        "application_id": app_ent["id"],
        "sprinkler_status": "UNDER_REVIEW", "alarm_status": "UNDER_REVIEW",
        "egress_status": "UNDER_REVIEW", "overall_status": "OPEN",
        "correction_cycles": 0,
    })
    db.plan_reviews[review["id"]] = review
    return ok(public(app_ent))


@app.route("/api/permit-applications/<aid>/pay-fee", methods=["POST"])
def pay_fee(aid):
    auth()
    require_role({"Applicant"})
    app_ent = find(db.permit_applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if g.user_id != app_ent["applicant_user_id"]:
        err("ERR_NOT_OWNER", "Caller is not the owning applicant")
    body = body_json()
    amount = require_int(body, "amount_cents", minimum=0)
    app_ent["amount_paid_cents"] += amount
    touch(app_ent)
    return ok(public(app_ent))


# ---------------------------------------------------------------------------
# PlanReview endpoints
# ---------------------------------------------------------------------------
@app.route("/api/plan-reviews/<rid>", methods=["GET"])
def get_plan_review(rid):
    auth()
    require_role(ROLES)
    review = find(db.plan_reviews, rid, "ERR_PLAN_REVIEW_NOT_FOUND")
    return ok(public(review))


@app.route("/api/plan-reviews", methods=["GET"])
def list_plan_reviews():
    auth()
    require_role(ROLES)
    items = list(db.plan_reviews.values())
    application_id = request.args.get("application_id")
    if application_id:
        items = [r for r in items if r["application_id"] == application_id]
    return list_response(items)


DISCIPLINE_FIELD = {"SPRINKLER": "sprinkler_status", "ALARM": "alarm_status", "EGRESS": "egress_status"}


@app.route("/api/plan-reviews/<rid>/discipline-decision", methods=["POST"])
def discipline_decision(rid):
    auth()
    require_role({"PlanReviewer"})
    review = find(db.plan_reviews, rid, "ERR_PLAN_REVIEW_NOT_FOUND")
    body = body_json()
    if "discipline" not in body or body["discipline"] is None:
        err("ERR_VALIDATION", "Missing required field: discipline")
    if "decision" not in body or body["decision"] is None:
        err("ERR_VALIDATION", "Missing required field: decision")
    discipline = require_enum(body["discipline"], DISCIPLINES, "discipline")
    decision = require_enum(body["decision"], DECISIONS, "decision")
    axis_field = DISCIPLINE_FIELD[discipline]
    # state: named axis must be UNDER_REVIEW (precedence 10)
    if review[axis_field] != "UNDER_REVIEW":
        err("ERR_REVIEW_INCOMPLETE", "Named discipline axis is not UNDER_REVIEW")
    app_ent = db.permit_applications.get(review["application_id"])
    review[axis_field] = decision
    if decision == "CORRECTIONS_REQUIRED":
        touch(review)
        if app_ent and app_ent["status"] == "UNDER_REVIEW":
            app_ent["status"] = "CORRECTIONS_REQUIRED"
            touch(app_ent)
    else:
        all_approved = all(review[f] == "APPROVED" for f in DISCIPLINE_FIELD.values())
        if all_approved:
            review["overall_status"] = "APPROVED"
        touch(review)
        if all_approved and app_ent and app_ent["status"] == "UNDER_REVIEW":
            app_ent["status"] = "APPROVED"
            touch(app_ent)
    return ok(public(review))


@app.route("/api/plan-reviews/<rid>/resubmit-corrections", methods=["POST"])
def resubmit_corrections(rid):
    auth()
    require_role({"Applicant"})
    review = find(db.plan_reviews, rid, "ERR_PLAN_REVIEW_NOT_FOUND")
    app_ent = db.permit_applications.get(review["application_id"])
    # ownership (precedence 4)
    if app_ent is None or g.user_id != app_ent["applicant_user_id"]:
        err("ERR_NOT_OWNER", "Caller is not the owning applicant")
    # state: at least one axis CORRECTIONS_REQUIRED (precedence 8)
    corrections = [f for f in DISCIPLINE_FIELD.values() if review[f] == "CORRECTIONS_REQUIRED"]
    if not corrections:
        err("ERR_INVALID_STATE", "No discipline axis is in CORRECTIONS_REQUIRED")
    for f in corrections:
        review[f] = "UNDER_REVIEW"
    review["correction_cycles"] += 1
    touch(review)
    app_ent["resubmit_count"] += 1
    if app_ent["status"] == "CORRECTIONS_REQUIRED":
        app_ent["status"] = "UNDER_REVIEW"
    touch(app_ent)
    return ok(public(review))


# ---------------------------------------------------------------------------
# Permit endpoints
# ---------------------------------------------------------------------------
@app.route("/api/permits", methods=["POST"])
def create_permit():
    auth()
    require_role({"FireMarshal"})
    body = body_json()
    if body.get("application_id"):
        find(db.permit_applications, body["application_id"], "ERR_APPLICATION_NOT_FOUND")
    application_id = require_str(body, "application_id")
    app_ent = find(db.permit_applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    # state: application APPROVED (precedence 9)
    if app_ent["status"] != "APPROVED":
        err("ERR_APPLICATION_NOT_APPROVED", "Application is not APPROVED")
    # compute final fee then check payment (precedence 16)
    final_fee = compute_permit_fee(app_ent["permit_type"], app_ent["project_valuation_cents"],
                                   app_ent["resubmit_count"])
    if app_ent["amount_paid_cents"] < final_fee:
        err("ERR_FEE_UNPAID", "Application is not paid in full")
    app_ent["final_fee_cents"] = final_fee
    db.permit_seq += 1
    issued_at = clock_now_iso()
    expires_at = to_iso(clock_now() + timedelta(days=PERMIT_EXPIRY_DAYS))
    permit = new_entity({
        "application_id": app_ent["id"],
        "permit_number": f"PERMIT-{db.permit_seq:06d}",
        "status": "ISSUED", "final_fee_cents": final_fee,
        "issued_at": issued_at, "expires_at": expires_at,
    })
    db.permits[permit["id"]] = permit
    app_ent["status"] = "ISSUED"
    touch(app_ent)
    prop = db.properties.get(app_ent["property_id"])
    if prop:
        prop["fees_paid_cents"] += final_fee
        touch(prop)
    return ok(public(permit), 201)


@app.route("/api/permits/<pid>", methods=["GET"])
def get_permit(pid):
    auth()
    require_role(ROLES)
    permit = find(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    return ok(public(permit))


@app.route("/api/permits", methods=["GET"])
def list_permits():
    auth()
    require_role(ROLES)
    items = list(db.permits.values())
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    if application_id:
        items = [p for p in items if p["application_id"] == application_id]
    if status:
        items = [p for p in items if p["status"] == status]
    return list_response(items)


@app.route("/api/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    auth()
    require_role({"FireMarshal"})
    permit = find(db.permits, pid, "ERR_PERMIT_NOT_FOUND")
    if permit["status"] != "ISSUED":
        err("ERR_INVALID_STATE", "Permit is not ISSUED")
    permit["status"] = "REVOKED"
    touch(permit)
    app_ent = db.permit_applications.get(permit["application_id"])
    fee = permit["final_fee_cents"]
    prop = None
    if app_ent:
        app_ent["refunded_cents"] += fee
        touch(app_ent)
        prop = db.properties.get(app_ent["property_id"])
    if prop:
        prop["fees_paid_cents"] -= fee
        touch(prop)
        # CASCADE: certificate for the property REVOKED + RED
        for cert in certificates_for_property(prop["id"]):
            cert["occupancy_status"] = "REVOKED"
            cert["placard_status"] = "RED"
            touch(cert)
    return ok(public(permit))


# ---------------------------------------------------------------------------
# Certificate endpoints
# ---------------------------------------------------------------------------
@app.route("/api/certificates", methods=["POST"])
def create_certificate():
    auth()
    require_role({"FireMarshal"})
    body = body_json()
    if body.get("property_id"):
        find(db.properties, body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    property_id = require_str(body, "property_id")
    find(db.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    if property_has_blocking_violation(property_id):
        err("ERR_OPEN_VIOLATIONS", "Property has OPEN or ESCALATED violations")
    cert = new_entity({
        "property_id": property_id,
        "occupancy_status": "VALID", "placard_status": "GREEN",
    })
    db.certificates[cert["id"]] = cert
    return ok(public(cert), 201)


@app.route("/api/certificates/<cid>", methods=["GET"])
def get_certificate(cid):
    auth()
    require_role(ROLES)
    cert = find(db.certificates, cid, "ERR_CERTIFICATE_NOT_FOUND")
    return ok(public(cert))


@app.route("/api/certificates", methods=["GET"])
def list_certificates():
    auth()
    require_role(ROLES)
    items = list(db.certificates.values())
    property_id = request.args.get("property_id")
    if property_id:
        items = [c for c in items if c["property_id"] == property_id]
    return list_response(items)


@app.route("/api/certificates/<cid>/reinstate", methods=["POST"])
def reinstate_certificate(cid):
    auth()
    require_role({"FireMarshal"})
    cert = find(db.certificates, cid, "ERR_CERTIFICATE_NOT_FOUND")
    # state: must be SUSPENDED (precedence 8)
    if cert["occupancy_status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Certificate is not SUSPENDED")
    # business: no OPEN/ESCALATED violation (precedence 11)
    if property_has_blocking_violation(cert["property_id"]):
        err("ERR_OPEN_VIOLATIONS", "Property has OPEN or ESCALATED violations")
    cert["occupancy_status"] = "VALID"
    cert["placard_status"] = "GREEN"
    touch(cert)
    return ok(public(cert))


# ---------------------------------------------------------------------------
# Inspection endpoints
# ---------------------------------------------------------------------------
@app.route("/api/inspections", methods=["POST"])
def create_inspection():
    auth()
    require_role({"Inspector"})
    body = body_json()
    if body.get("property_id"):
        find(db.properties, body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    property_id = require_str(body, "property_id")
    find(db.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    if "inspection_type" not in body or body["inspection_type"] is None:
        err("ERR_VALIDATION", "Missing required field: inspection_type")
    scheduled_date = require_str(body, "scheduled_date")
    itype = require_enum(body["inspection_type"], INSPECTION_TYPES, "inspection_type")
    # conditional field (precedence 7)
    complaint_description = body.get("complaint_description")
    if itype == "COMPLAINT" and (complaint_description is None or complaint_description == ""):
        err("ERR_MISSING_CONDITIONAL_FIELD", "COMPLAINT inspection requires complaint_description")
    if itype != "COMPLAINT":
        complaint_description = None
    try:
        sched_dt = parse_dt(scheduled_date)
    except (ValueError, TypeError):
        err("ERR_VALIDATION", "scheduled_date must be an ISO8601 datetime")
    # temporal buffer (precedence 13): symmetric 14-day buffer vs non-terminal inspections
    for other in db.inspections.values():
        if other["property_id"] != property_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        other_dt = parse_dt(other["scheduled_date"])
        diff_days = abs((sched_dt - other_dt).total_seconds()) / 86400.0
        if diff_days < INSPECTION_BUFFER_DAYS:
            err("ERR_INSPECTION_TOO_CLOSE", "Inspection too close to an existing scheduled inspection")
    insp = new_entity({
        "property_id": property_id, "inspection_type": itype,
        "complaint_description": complaint_description,
        "scheduled_date": scheduled_date, "status": "SCHEDULED",
        "result_recorded_at": None,
    })
    db.inspections[insp["id"]] = insp
    return ok(public(insp), 201)


@app.route("/api/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    auth()
    require_role(ROLES)
    insp = find(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    return ok(public(insp))


@app.route("/api/inspections", methods=["GET"])
def list_inspections():
    auth()
    require_role(ROLES)
    items = list(db.inspections.values())
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    itype = request.args.get("inspection_type")
    if property_id:
        items = [i for i in items if i["property_id"] == property_id]
    if status:
        items = [i for i in items if i["status"] == status]
    if itype:
        items = [i for i in items if i["inspection_type"] == itype]
    return list_response(items)


def create_violation(insp, code_section, severity):
    prop = db.properties.get(insp["property_id"])
    viol = new_entity({
        "inspection_id": insp["id"], "code_section": code_section,
        "severity": severity, "status": "OPEN", "abated_at": None,
    })
    db.violations[viol["id"]] = viol
    if prop:
        prop["open_violation_count"] += 1
        touch(prop)
    return viol


def auto_issue_abatement_order(viol):
    """Cascade C1 hop2: auto-create ISSUED active abatement order."""
    grace = ABATEMENT_GRACE_DAYS[viol["severity"]]
    order = new_entity({
        "violation_id": viol["id"],
        "issued_at": clock_now_iso(),
        "deadline": to_iso(clock_now() + timedelta(days=grace)),
        "status": "ISSUED", "is_active": True,
    })
    db.abatement_orders[order["id"]] = order
    return order


@app.route("/api/inspections/<iid>/record-result", methods=["POST"])
def record_result(iid):
    auth()
    require_role({"Inspector"})
    insp = find(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    body = body_json()
    if "result" not in body or body["result"] is None:
        err("ERR_VALIDATION", "Missing required field: result")
    result = require_enum(body["result"], RESULTS, "result")
    # state (precedence 8)
    if insp["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Inspection is not SCHEDULED")
    itype = insp["inspection_type"]
    findings = body.get("findings")
    if result == "FAILED":
        if itype != "RE_INSPECTION":
            if not isinstance(findings, list) or len(findings) == 0:
                err("ERR_VALIDATION", "FAILED result requires a non-empty findings array")
        # validate findings entries if present
        if findings is not None:
            if not isinstance(findings, list):
                err("ERR_VALIDATION", "findings must be an array")
            for fnd in findings:
                if not isinstance(fnd, dict):
                    err("ERR_VALIDATION", "each finding must be an object")
                if "code_section" not in fnd or not isinstance(fnd["code_section"], str) or fnd["code_section"] == "":
                    err("ERR_VALIDATION", "each finding requires code_section")
                if "severity" not in fnd or fnd["severity"] is None:
                    err("ERR_VALIDATION", "each finding requires severity")
                require_enum(fnd["severity"], SEVERITIES, "severity")
        # apply
        insp["result_recorded_at"] = clock_now_iso()
        insp["status"] = "FAILED"
        touch(insp)
        imminent_seen = False
        for fnd in (findings or []):
            viol = create_violation(insp, fnd["code_section"], fnd["severity"])
            if viol["severity"] == "IMMINENT_HAZARD":
                imminent_seen = True
                auto_issue_abatement_order(viol)
                suspend_certificates(insp["property_id"])
        # RE_INSPECTION FAILED reopens ABATED violations on the property
        if itype == "RE_INSPECTION":
            prop = db.properties.get(insp["property_id"])
            for viol in violations_for_property(insp["property_id"]):
                if viol["status"] == "ABATED":
                    viol["status"] = "OPEN"
                    touch(viol)
                    if prop:
                        prop["open_violation_count"] += 1
                        touch(prop)
                    if viol["severity"] == "IMMINENT_HAZARD":
                        imminent_seen = True
        # no imminent produced/reopened -> drop placard to YELLOW if a cert exists
        if not imminent_seen:
            for cert in certificates_for_property(insp["property_id"]):
                cert["placard_status"] = "YELLOW"
                touch(cert)
    else:  # PASSED
        insp["result_recorded_at"] = clock_now_iso()
        insp["status"] = "PASSED"
        touch(insp)
        if itype == "RE_INSPECTION":
            for viol in violations_for_property(insp["property_id"]):
                if viol["status"] == "ABATED":
                    viol["status"] = "VERIFIED"
                    touch(viol)
    return ok(public(insp))


# ---------------------------------------------------------------------------
# Violation / AbatementOrder endpoints
# ---------------------------------------------------------------------------
@app.route("/api/violations/<vid>", methods=["GET"])
def get_violation(vid):
    auth()
    require_role(ROLES)
    viol = find(db.violations, vid, "ERR_VIOLATION_NOT_FOUND")
    return ok(public(viol))


@app.route("/api/violations", methods=["GET"])
def list_violations():
    auth()
    require_role(ROLES)
    items = list(db.violations.values())
    inspection_id = request.args.get("inspection_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    if inspection_id:
        items = [v for v in items if v["inspection_id"] == inspection_id]
    if property_id:
        keep = set()
        for v in items:
            insp = db.inspections.get(v["inspection_id"])
            if insp and insp["property_id"] == property_id:
                keep.add(v["id"])
        items = [v for v in items if v["id"] in keep]
    if status:
        items = [v for v in items if v["status"] == status]
    return list_response(items)


@app.route("/api/violations/<vid>/abatement-orders", methods=["POST"])
def create_abatement_order(vid):
    auth()
    require_role({"Inspector"})
    viol = find(db.violations, vid, "ERR_VIOLATION_NOT_FOUND")
    body = body_json()
    # required field expected_violation_version (precedence 5)
    expected = require_int(body, "expected_violation_version")
    # OCC (precedence 17)
    if expected != viol["version"]:
        err("ERR_STALE_VERSION", "expected_violation_version does not match current version")
    # supersede prior active ISSUED order
    for order in db.abatement_orders.values():
        if order["violation_id"] == viol["id"] and order["is_active"]:
            if order["status"] == "ISSUED":
                order["status"] = "SUPERSEDED"
            order["is_active"] = False
            touch(order)
    grace = ABATEMENT_GRACE_DAYS[viol["severity"]]
    order = new_entity({
        "violation_id": viol["id"],
        "issued_at": clock_now_iso(),
        "deadline": to_iso(clock_now() + timedelta(days=grace)),
        "status": "ISSUED", "is_active": True,
    })
    db.abatement_orders[order["id"]] = order
    touch(viol)  # increment violation.version by 1
    return ok(public(order), 201)


@app.route("/api/abatement-orders/<oid>", methods=["GET"])
def get_abatement_order(oid):
    auth()
    require_role(ROLES)
    order = find(db.abatement_orders, oid, "ERR_ABATEMENT_ORDER_NOT_FOUND")
    return ok(public(order))


@app.route("/api/abatement-orders", methods=["GET"])
def list_abatement_orders():
    auth()
    require_role(ROLES)
    items = list(db.abatement_orders.values())
    violation_id = request.args.get("violation_id")
    status = request.args.get("status")
    if violation_id:
        items = [o for o in items if o["violation_id"] == violation_id]
    if status:
        items = [o for o in items if o["status"] == status]
    return list_response(items)


@app.route("/api/abatement-orders/<oid>/comply", methods=["POST"])
def comply_abatement_order(oid):
    auth()
    require_role({"Inspector"})
    order = find(db.abatement_orders, oid, "ERR_ABATEMENT_ORDER_NOT_FOUND")
    viol = db.violations.get(order["violation_id"])
    # state: order ISSUED + is_active and violation OPEN (precedence 8)
    if order["status"] != "ISSUED" or not order["is_active"] or viol is None or viol["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Order is not compliable in current state")
    order["status"] = "COMPLIED"
    touch(order)
    viol["status"] = "ABATED"
    viol["abated_at"] = clock_now_iso()
    touch(viol)
    prop = db.properties.get(db.inspections.get(viol["inspection_id"], {}).get("property_id"))
    if prop:
        prop["open_violation_count"] -= 1
        touch(prop)
    return ok(public(order))


# ---------------------------------------------------------------------------
# Hydrant endpoints
# ---------------------------------------------------------------------------
@app.route("/api/hydrants", methods=["POST"])
def create_hydrant():
    auth()
    require_role({"Inspector", "FireMarshal"})
    body = body_json()
    if body.get("property_id"):
        find(db.properties, body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    property_id = require_str(body, "property_id")
    find(db.properties, property_id, "ERR_PROPERTY_NOT_FOUND")
    location_desc = require_str(body, "location_desc")
    main_size = require_number(body, "main_size_inches")
    hyd = new_entity({
        "property_id": property_id, "location_desc": location_desc,
        "main_size_inches": main_size,
    })
    db.hydrants[hyd["id"]] = hyd
    return ok(public(hyd), 201)


@app.route("/api/hydrants/<hid>", methods=["GET"])
def get_hydrant(hid):
    auth()
    require_role(ROLES)
    hyd = find(db.hydrants, hid, "ERR_HYDRANT_NOT_FOUND")
    return ok(public(hyd))


@app.route("/api/hydrants", methods=["GET"])
def list_hydrants():
    auth()
    require_role(ROLES)
    items = list(db.hydrants.values())
    property_id = request.args.get("property_id")
    if property_id:
        items = [h for h in items if h["property_id"] == property_id]
    return list_response(items)


# ---------------------------------------------------------------------------
# FlowTest endpoints
# ---------------------------------------------------------------------------
@app.route("/api/flow-tests", methods=["POST"])
def create_flow_test():
    auth()
    require_role({"Inspector"})
    body = body_json()
    if body.get("hydrant_id"):
        find(db.hydrants, body["hydrant_id"], "ERR_HYDRANT_NOT_FOUND")
    hydrant_id = require_str(body, "hydrant_id")
    find(db.hydrants, hydrant_id, "ERR_HYDRANT_NOT_FOUND")
    test_date = require_str(body, "test_date")
    static_psi = require_number(body, "static_psi")
    residual_psi = require_number(body, "residual_psi")
    measured_flow_gpm = require_number(body, "measured_flow_gpm")
    try:
        test_dt = parse_dt(test_date)
    except (ValueError, TypeError):
        err("ERR_VALIDATION", "test_date must be an ISO8601 datetime")
    # readings validity first (PRD §3.2 order overrides scaffold priority)
    if not (RESIDUAL_TARGET_PSI < residual_psi < static_psi) or measured_flow_gpm <= 0:
        err("ERR_INVALID_FLOW_READINGS", "Flow test readings are not physically coherent")
    # window overlap on same hydrant
    new_start = test_dt
    new_end = test_dt + timedelta(days=FLOW_TEST_WINDOW_DAYS)
    for other in db.flow_tests.values():
        if other["hydrant_id"] != hydrant_id:
            continue
        o_start = parse_dt(other["test_date"])
        o_end = o_start + timedelta(days=FLOW_TEST_WINDOW_DAYS)
        if new_start < o_end and o_start < new_end:
            err("ERR_FLOW_TEST_WINDOW_OVERLAP", "Flow test window overlaps an existing window")
    available = compute_available_flow(static_psi, residual_psi, measured_flow_gpm)
    ft = new_entity({
        "hydrant_id": hydrant_id, "test_date": test_date,
        "static_psi": static_psi, "residual_psi": residual_psi,
        "measured_flow_gpm": measured_flow_gpm,
        "available_flow_at_20psi": available,
        "valid_until": to_iso(new_end),
    })
    db.flow_tests[ft["id"]] = ft
    return ok(public(ft), 201)


@app.route("/api/flow-tests/<fid>", methods=["GET"])
def get_flow_test(fid):
    auth()
    require_role(ROLES)
    ft = find(db.flow_tests, fid, "ERR_FLOW_TEST_NOT_FOUND")
    return ok(public(ft))


@app.route("/api/flow-tests", methods=["GET"])
def list_flow_tests():
    auth()
    require_role(ROLES)
    items = list(db.flow_tests.values())
    hydrant_id = request.args.get("hydrant_id")
    if hydrant_id:
        items = [f for f in items if f["hydrant_id"] == hydrant_id]
    return list_response(items)


# ---------------------------------------------------------------------------
# Ops / logical clock
# ---------------------------------------------------------------------------
@app.route("/api/_ops/process-overdue-orders", methods=["POST"])
def process_overdue_orders():
    auth()
    require_role({"FireMarshal"})
    now = clock_now()
    processed_count = 0
    escalated_violation_ids = []
    # snapshot list (insertion order) to iterate deterministically
    for order in sorted(db.abatement_orders.values(), key=lambda e: e["_seq"]):
        if order["status"] != "ISSUED" or not order["is_active"]:
            continue
        deadline = parse_dt(order["deadline"])
        if now > deadline:
            # order ISSUED -> OVERDUE -> ESCALATED
            order["status"] = "ESCALATED"
            order["is_active"] = False
            touch(order)
            processed_count += 1
            viol = db.violations.get(order["violation_id"])
            if viol and viol["status"] == "OPEN":
                viol["status"] = "ESCALATED"
                touch(viol)
                escalated_violation_ids.append(viol["id"])
                insp = db.inspections.get(viol["inspection_id"])
                if insp:
                    prop = db.properties.get(insp["property_id"])
                    if prop:
                        prop["open_violation_count"] -= 1
                        touch(prop)
                    # C2 hop2: suspend certificate
                    suspend_certificates(insp["property_id"])
    return ok({"processed_count": processed_count,
               "escalated_violation_ids": escalated_violation_ids})


@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth()
    require_role({"FireMarshal"})
    body = body_json()
    to_iso8601 = require_str(body, "to_iso8601")
    try:
        db.clock = parse_dt(to_iso8601)
    except (ValueError, TypeError):
        err("ERR_VALIDATION", "to_iso8601 must be an ISO8601 datetime")
    return ok({})


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
db = Store()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
