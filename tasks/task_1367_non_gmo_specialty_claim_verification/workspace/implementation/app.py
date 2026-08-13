#!/usr/bin/env python3
"""Non-GMO & Specialty Claim Verification API.

In-memory Flask implementation of the PRD. Storage is Python dicts only;
the store starts empty on every boot. All temporal rules are evaluated
against a server-side logical clock (default 2026-08-01T00:00:00Z).
"""

import calendar
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLES = {"VerifierAdmin", "BrandRep", "LabAnalyst", "Auditor", "EnforcementOfficer"}

ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT"
ERR_VALID = "ERR_VALIDATION"
ERR_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_BRAND = "ERR_NOT_BRAND_RESOURCE"
ERR_SOD = "ERR_SEGREGATION_OF_DUTIES"
ERR_NOT_AUDITOR = "ERR_NOT_ASSIGNED_AUDITOR"
ERR_PROBATION = "ERR_BRAND_ON_PROBATION"
ERR_RECENT = "ERR_BRAND_RECENT_PENALTIES"
ERR_NF = "ERR_NOT_FOUND"
ERR_PRODUCT_STATE = "ERR_PRODUCT_INVALID_STATE"
ERR_NO_INGREDIENTS = "ERR_NO_INGREDIENTS"
ERR_PLAN_STATE = "ERR_PLAN_NOT_ACTIVE"
ERR_SAMPLE_STATE = "ERR_SAMPLE_INVALID_STATE"
ERR_AUDIT_STATE = "ERR_AUDIT_INVALID_STATE"
ERR_CASE_STATE = "ERR_CASE_NOT_OPEN"
ERR_AFF_STATE = "ERR_AFFIDAVIT_NOT_REVIEWABLE"
ERR_AFF_MISSING = "ERR_AFFIDAVIT_MISSING"
ERR_AFF_OVERLAP = "ERR_AFFIDAVIT_WINDOW_OVERLAP"
ERR_RENEWAL_CLOSED = "ERR_RENEWAL_WINDOW_CLOSED"
ERR_AUDIT_NOT_PASSED = "ERR_AUDIT_NOT_PASSED"
ERR_AUDIT_STALE = "ERR_AUDIT_STALE"
ERR_OPEN_CASE = "ERR_OPEN_ENFORCEMENT_CASE"
ERR_NON_COMPLIANT = "ERR_NON_COMPLIANT_RESULTS_EXIST"
ERR_PENDING = "ERR_INGREDIENTS_PENDING"
ERR_INCOMPLETE_SAMPLING = "ERR_INCOMPLETE_SAMPLING"
ERR_AUDIT_CAPACITY = "ERR_AUDIT_CAPACITY_CONFLICT"
ERR_TRACE_LOW = "ERR_TRACE_SCORE_BELOW_MIN"
ERR_GTIN = "ERR_PRODUCT_GTIN_EXISTS"
ERR_NOT_TESTABLE = "ERR_INGREDIENT_NOT_TESTABLE"
ERR_XREF = "ERR_CROSS_REFERENCE_MISMATCH"
ERR_WEIGHT_SUM = "ERR_WEIGHT_SUM_EXCEEDED"
ERR_STALE = "ERR_STALE_VERSION"

PRODUCT_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_EVALUATION", "VERIFIED", "REJECTED",
                    "RENEWAL_DUE", "SUSPENDED", "REVOKED", "LAPSED"]
CROP_TYPES = ["HIGH_RISK", "LOW_RISK", "NON_CROP"]
RISK_POINTS = ["INGREDIENT_INTAKE", "IN_PROCESS", "FINISHED_PRODUCT"]
SOURCES = ["CONSUMER_COMPLAINT", "MARKETPLACE_MONITOR", "RETEST_FAILURE"]
SANCTIONS = ["WARNING", "LICENSE_SUSPENSION", "LICENSE_REVOCATION"]
PENALTY = {"WARNING": 5, "LICENSE_SUSPENSION": 15, "LICENSE_REVOCATION": 25}
PLAN_BASE = {"INGREDIENT_INTAKE": 0, "IN_PROCESS": 1, "FINISHED_PRODUCT": 2}

CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}
SEQ = {"n": 0}
LIC_SEQ = {"n": 0}

standards = {}
brands = {}
products = {}
ingredients = {}
affidavits = {}
plans = {}
samples = {}
audits = {}
licenses = {}
cases = {}


# ---------------------------------------------------------------------------
# Errors and envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def fail(error_id, status, message):
    raise ApiError(error_id, status, message)


def now():
    return CLOCK["now"]


def fmt3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """ISO 8601 UTC; fractional digits only when present."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field):
    if not isinstance(value, str):
        fail(ERR_VALID, 400, "Field '%s' must be an ISO 8601 datetime string" % field)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(ERR_VALID, 400, "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + int(months)
    y, m0 = divmod(total, 12)
    m = m0 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def dec(v):
    return Decimal(str(v))


def make_meta(pagination=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": fmt3(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, rtype="object", status=200, pagination=None):
    body = {"meta": make_meta(pagination), "response_type": rtype, "data": data}
    return jsonify(body), status


def error_response(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError(ERR_NF, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError(ERR_NF, 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_500(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


# ---------------------------------------------------------------------------
# Auth / shape helpers
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail(ERR_AUTH, 400, "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        fail(ERR_ROLE, 403, "Role %s is not permitted for this operation" % role)


def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail(ERR_VALID, 400, "Request body must be a JSON object")
    return data


def check_allowed(data, allowed):
    for k in data:
        if k not in allowed:
            fail(ERR_VALID, 400, "Unknown or computed field in body: %s" % k)


def req_str(data, field, required=True, non_empty=False):
    if field not in data or data[field] is None:
        if required:
            fail(ERR_VALID, 400, "Missing required field: %s" % field)
        return None
    v = data[field]
    if not isinstance(v, str) or (non_empty and v.strip() == ""):
        fail(ERR_VALID, 400, "Field '%s' must be a %sstring" % (field, "non-empty " if non_empty else ""))
    return v


def req_num(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            fail(ERR_VALID, 400, "Missing required field: %s" % field)
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(ERR_VALID, 400, "Field '%s' must be a number" % field)
    return v


def req_int(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            fail(ERR_VALID, 400, "Missing required field: %s" % field)
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_VALID, 400, "Field '%s' must be an integer" % field)
    return v


def req_enum(data, field, choices, required=True):
    v = req_str(data, field, required=required)
    if v is None:
        return None
    if v not in choices:
        fail(ERR_VALID, 400, "Field '%s' must be one of %s" % (field, choices))
    return v


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def new_rec():
    SEQ["n"] += 1
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": SEQ["n"],
    }


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def get_rec(store, rid, what="Resource"):
    rec = store.get(rid)
    if rec is None:
        fail(ERR_NF, 404, "%s not found: %s" % (what, rid))
    return rec


def ingredients_of(product_id):
    return [i for i in ingredients.values() if i["product_id"] == product_id]


def affidavits_of(ingredient_id):
    return [a for a in affidavits.values() if a["ingredient_id"] == ingredient_id]


def samples_of_ingredient(ingredient_id):
    return [s for s in samples.values() if s["ingredient_id"] == ingredient_id]


def samples_of_plan(plan_id):
    return [s for s in samples.values() if s["sampling_plan_id"] == plan_id]


def plans_of_product(product_id):
    return [p for p in plans.values() if p["product_id"] == product_id]


def cases_of_product(product_id):
    return [c for c in cases.values() if c["product_id"] == product_id]


def audits_of_brand(brand_id):
    return [a for a in audits.values() if a["brand_id"] == brand_id]


def products_of_brand(brand_id):
    return [p for p in products.values() if p["brand_id"] == brand_id]


def license_of_product(product_id):
    for lic in licenses.values():
        if lic["product_id"] == product_id:
            return lic
    return None


def product_standard(product):
    return standards[product["standard_id"]]


def affidavit_current(ingredient_id):
    t = now()
    for a in affidavits_of(ingredient_id):
        if a["status"] == "ACCEPTED" and a["valid_from"] <= t < a["valid_until"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Derived-state recomputation
# ---------------------------------------------------------------------------

def recompute_ingredient(ing):
    confirmed = [s for s in samples_of_ingredient(ing["id"]) if s["status"] == "CONFIRMED"]
    if any(s["outcome"] == "NON_COMPLIANT" for s in confirmed):
        new = "NON_COMPLIANT"
    elif not ing["requires_pcr"] and not ing["requires_affidavit"]:
        # an ingredient that requires neither testing nor paperwork is EXEMPTED
        new = "EXEMPTED"
    else:
        satisfied = True
        if ing["requires_pcr"] and not any(s["outcome"] == "COMPLIANT" for s in confirmed):
            satisfied = False
        if ing["requires_affidavit"] and not affidavit_current(ing["id"]):
            satisfied = False
        new = "COMPLIANT" if satisfied else "PENDING"
    if new != ing["compliance_status"]:
        ing["compliance_status"] = new
        touch(ing)


def recompute_exposure(product, bump=True):
    standard = product_standard(product)
    prov = Decimal(0)
    conf = Decimal(0)
    for ing in ingredients_of(product["id"]):
        confirmed = [s for s in samples_of_ingredient(ing["id"]) if s["status"] == "CONFIRMED"]
        r = max((dec(s["result_gmo_pct"]) for s in confirmed), default=None)
        w = dec(ing["declared_weight_pct"])
        if r is not None:
            c_prov = r
            c_conf = r
        else:
            c_prov = dec(standard["ingredient_threshold_pct"]) if ing["requires_pcr"] else Decimal(0)
            c_conf = Decimal(0)
        prov += w * c_prov
        conf += w * c_conf
    new_prov = prov.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    new_conf = conf.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if new_prov != product["provisional_exposure_pct"] or new_conf != product["confirmed_exposure_pct"]:
        product["provisional_exposure_pct"] = new_prov
        product["confirmed_exposure_pct"] = new_conf
        if bump:
            touch(product)


def recompute_brand(brand):
    t = now()
    sub_cases = []
    for p in products_of_brand(brand["id"]):
        for c in cases_of_product(p["id"]):
            if c["status"] == "SUBSTANTIATED":
                sub_cases.append(c)
    lifetime = sum(c["penalty_points"] for c in sub_cases)
    window_start = t - timedelta(days=365)
    rolling = sum(c["penalty_points"] for c in sub_cases if c["substantiated_at"] > window_start)
    standing = "PROBATION" if lifetime >= 20 else "GOOD_STANDING"
    count = len([p for p in products_of_brand(brand["id"])
                 if p["enrollment_status"] in ("VERIFIED", "RENEWAL_DUE")])
    if (brand["lifetime_penalty_points"] != lifetime
            or brand["rolling_penalty_points"] != rolling
            or brand["standing_status"] != standing
            or brand["verified_product_count"] != count):
        brand["lifetime_penalty_points"] = lifetime
        brand["rolling_penalty_points"] = rolling
        brand["standing_status"] = standing
        brand["verified_product_count"] = count
        touch(brand)


def most_recent_passed_audit(brand_id):
    passed = [a for a in audits_of_brand(brand_id) if a["status"] == "PASSED"]
    if not passed:
        return None
    # latest decided_at; ties broken by earliest created_at
    return sorted(passed, key=lambda a: (-a["decided_at"].timestamp(), a["created_at"], a["_seq"]))[0]


def audit_fresh(standard, brand_id):
    audit = most_recent_passed_audit(brand_id)
    if audit is None:
        return False
    return add_months(audit["decided_at"], standard["audit_validity_months"]) > now()


def compute_required_sample_count(product, risk_point):
    base = PLAN_BASE[risk_point]
    pcr_count = len([i for i in ingredients_of(product["id"]) if i["requires_pcr"]])
    vol = product["annual_volume_units"]
    volume_extra = 2 if vol >= 100000 else (1 if vol >= 10000 else 0)
    brand_cases = [c for p in products_of_brand(product["brand_id"])
                   for c in cases_of_product(p["id"]) if c["status"] == "SUBSTANTIATED"]
    brand_failed = [a for a in audits_of_brand(product["brand_id"]) if a["status"] == "FAILED"]
    history_extra = 2 if (brand_cases or brand_failed) else 0
    return min(10, base + pcr_count + volume_extra + history_extra)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def base_view(r):
    return {
        "id": r["id"],
        "created_at": fmt3(r["created_at"]),
        "updated_at": fmt3(r["updated_at"]),
        "version": r["version"],
    }


def num(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def std_view(s):
    v = base_view(s)
    v.update({
        "claim_code": s["claim_code"],
        "name": s["name"],
        "ingredient_threshold_pct": s["ingredient_threshold_pct"],
        "exemption_max_weight_pct": s["exemption_max_weight_pct"],
        "audit_validity_months": s["audit_validity_months"],
        "renewal_window_days": s["renewal_window_days"],
        "license_term_days": s["license_term_days"],
    })
    return v


def brand_view(b):
    v = base_view(b)
    v.update({
        "name": b["name"],
        "contact_email": b["contact_email"],
        "lifetime_penalty_points": b["lifetime_penalty_points"],
        "rolling_penalty_points": b["rolling_penalty_points"],
        "standing_status": b["standing_status"],
        "verified_product_count": b["verified_product_count"],
    })
    return v


def product_view(p):
    v = base_view(p)
    v.update({
        "brand_id": p["brand_id"],
        "standard_id": p["standard_id"],
        "name": p["name"],
        "gtin": p["gtin"],
        "annual_volume_units": p["annual_volume_units"],
        "enrollment_status": p["enrollment_status"],
        "rejection_reason": p["rejection_reason"],
        "provisional_exposure_pct": num(p["provisional_exposure_pct"]),
        "confirmed_exposure_pct": num(p["confirmed_exposure_pct"]),
    })
    return v


def ingredient_view(i):
    v = base_view(i)
    v.update({
        "product_id": i["product_id"],
        "name": i["name"],
        "crop_type": i["crop_type"],
        "declared_weight_pct": i["declared_weight_pct"],
        "is_exempt": i["is_exempt"],
        "requires_pcr": i["requires_pcr"],
        "requires_affidavit": i["requires_affidavit"],
        "compliance_status": i["compliance_status"],
    })
    return v


def affidavit_view(a):
    v = base_view(a)
    v.update({
        "ingredient_id": a["ingredient_id"],
        "supplier_name": a["supplier_name"],
        "valid_from": fmt_dt(a["valid_from"]),
        "valid_until": fmt_dt(a["valid_until"]),
        "status": a["status"],
        "submitted_by_user_id": a["submitted_by_user_id"],
    })
    return v


def plan_view(p):
    v = base_view(p)
    v.update({
        "product_id": p["product_id"],
        "risk_point": p["risk_point"],
        "required_sample_count": p["required_sample_count"],
        "confirmed_sample_count": p["confirmed_sample_count"],
        "status": p["status"],
        "superseded_by_plan_id": p["superseded_by_plan_id"],
    })
    return v


def sample_view(s):
    v = base_view(s)
    v.update({
        "sampling_plan_id": s["sampling_plan_id"],
        "ingredient_id": s["ingredient_id"],
        "result_gmo_pct": s["result_gmo_pct"],
        "outcome": s["outcome"],
        "recorded_by_user_id": s["recorded_by_user_id"],
        "confirmed_by_user_id": s["confirmed_by_user_id"],
        "status": s["status"],
    })
    return v


def audit_view(a):
    v = base_view(a)
    v.update({
        "brand_id": a["brand_id"],
        "facility_name": a["facility_name"],
        "auditor_id": a["auditor_id"],
        "scheduled_date": fmt_dt(a["scheduled_date"]),
        "lots": a["lots"],
        "traceability_score_pct": num(a["traceability_score_pct"]) if a["traceability_score_pct"] is not None else None,
        "decided_at": fmt_dt(a["decided_at"]),
        "status": a["status"],
    })
    return v


def license_view(lic):
    v = base_view(lic)
    v.update({
        "product_id": lic["product_id"],
        "license_code": lic["license_code"],
        "valid_from": fmt_dt(lic["valid_from"]),
        "valid_until": fmt_dt(lic["valid_until"]),
        "suspended_at": fmt_dt(lic["suspended_at"]),
        "suspend_reason": lic["suspend_reason"],
        "status": lic["status"],
    })
    return v


def case_view(c):
    v = base_view(c)
    v.update({
        "product_id": c["product_id"],
        "source": c["source"],
        "description": c["description"],
        "opened_by_user_id": c["opened_by_user_id"],
        "resolved_by_user_id": c["resolved_by_user_id"],
        "sanction": c["sanction"],
        "penalty_points": c["penalty_points"],
        "substantiated_at": fmt_dt(c["substantiated_at"]),
        "status": c["status"],
    })
    return v


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------

def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def filter_exact(items, field, value):
    if value is None:
        return items
    return [i for i in items if i.get(field) == value]


# ---------------------------------------------------------------------------
# Claim standards
# ---------------------------------------------------------------------------

@app.route("/claim-standards", methods=["POST"])
def create_standard():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"claim_code", "name", "ingredient_threshold_pct",
                         "exemption_max_weight_pct", "audit_validity_months",
                         "renewal_window_days", "license_term_days"})
    claim_code = req_str(data, "claim_code")
    name = req_str(data, "name")
    threshold = req_num(data, "ingredient_threshold_pct")
    if not dec(threshold) > 0:
        fail(ERR_VALID, 400, "ingredient_threshold_pct must be > 0")
    exemption = req_num(data, "exemption_max_weight_pct")
    if not dec(exemption) >= 0:
        fail(ERR_VALID, 400, "exemption_max_weight_pct must be >= 0")
    avm = req_int(data, "audit_validity_months", required=False)
    rwd = req_int(data, "renewal_window_days", required=False)
    ltd = req_int(data, "license_term_days", required=False)
    for lbl, v in (("audit_validity_months", avm), ("renewal_window_days", rwd), ("license_term_days", ltd)):
        if v is not None and v < 0:
            fail(ERR_VALID, 400, "%s must be >= 0" % lbl)
    require_role(role, {"VerifierAdmin"})
    for s in standards.values():
        if s["claim_code"] == claim_code:
            fail(ERR_VALID, 400, "claim_code already exists: %s" % claim_code)
    rec = new_rec()
    rec.update({
        "claim_code": claim_code,
        "name": name,
        "ingredient_threshold_pct": threshold,
        "exemption_max_weight_pct": exemption,
        "audit_validity_months": avm if avm is not None else 12,
        "renewal_window_days": rwd if rwd is not None else 60,
        "license_term_days": ltd if ltd is not None else 365,
    })
    standards[rec["id"]] = rec
    return ok(std_view(rec), status=201)


@app.route("/claim-standards", methods=["GET"])
def list_standards():
    auth()
    items = filter_exact(list(standards.values()), "claim_code", request.args.get("claim_code"))
    page, pagination = paginate(items)
    return ok([std_view(s) for s in page], rtype="array", pagination=pagination)


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------

@app.route("/brands", methods=["POST"])
def create_brand():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"name", "contact_email"})
    name = req_str(data, "name")
    contact_email = req_str(data, "contact_email")
    require_role(role, {"VerifierAdmin"})
    rec = new_rec()
    rec.update({
        "name": name,
        "contact_email": contact_email,
        "lifetime_penalty_points": 0,
        "rolling_penalty_points": 0,
        "standing_status": "GOOD_STANDING",
        "verified_product_count": 0,
    })
    brands[rec["id"]] = rec
    return ok(brand_view(rec), status=201)


@app.route("/brands/<bid>", methods=["GET"])
def get_brand(bid):
    auth()
    return ok(brand_view(get_rec(brands, bid, "Brand")))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

def check_product_ownership(product, uid):
    if product["brand_id"] != uid:
        fail(ERR_NOT_BRAND, 403, "BrandRep does not own this product's brand")


@app.route("/products", methods=["POST"])
def create_product():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"brand_id", "standard_id", "name", "gtin", "annual_volume_units"})
    brand_id = req_str(data, "brand_id")
    standard_id = req_str(data, "standard_id")
    name = req_str(data, "name")
    gtin = req_str(data, "gtin")
    volume = req_int(data, "annual_volume_units")
    if volume < 0:
        fail(ERR_VALID, 400, "annual_volume_units must be >= 0")
    require_role(role, {"BrandRep"})
    brand = get_rec(brands, brand_id, "Brand")
    get_rec(standards, standard_id, "ClaimStandard")
    if brand_id != uid:
        fail(ERR_NOT_BRAND, 403, "BrandRep may only enroll products for their own brand")
    if brand["standing_status"] != "GOOD_STANDING":
        fail(ERR_PROBATION, 403, "Brand is on probation and cannot enroll products")
    for p in products.values():
        if p["standard_id"] == standard_id and p["gtin"] == gtin:
            fail(ERR_GTIN, 409, "gtin already exists under this standard")
    rec = new_rec()
    rec.update({
        "brand_id": brand_id,
        "standard_id": standard_id,
        "name": name,
        "gtin": gtin,
        "annual_volume_units": volume,
        "enrollment_status": "DRAFT",
        "rejection_reason": None,
        "provisional_exposure_pct": Decimal("0"),
        "confirmed_exposure_pct": Decimal("0"),
    })
    products[rec["id"]] = rec
    return ok(product_view(rec), status=201)


@app.route("/products", methods=["GET"])
def list_products():
    auth()
    items = list(products.values())
    items = filter_exact(items, "brand_id", request.args.get("brand_id"))
    items = filter_exact(items, "standard_id", request.args.get("standard_id"))
    items = filter_exact(items, "enrollment_status", request.args.get("enrollment_status"))
    page, pagination = paginate(items)
    return ok([product_view(p) for p in page], rtype="array", pagination=pagination)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    auth()
    return ok(product_view(get_rec(products, pid, "Product")))


def affidavit_currency_ok(product):
    for ing in ingredients_of(product["id"]):
        if ing["requires_affidavit"] and not affidavit_current(ing["id"]):
            return False
    return True


@app.route("/products/<pid>/submit", methods=["POST"])
def submit_product(pid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"BrandRep"})
    product = get_rec(products, pid, "Product")
    check_product_ownership(product, uid)
    if product["enrollment_status"] != "DRAFT":
        fail(ERR_PRODUCT_STATE, 409, "Submit requires enrollment_status DRAFT")
    if not ingredients_of(pid):
        fail(ERR_NO_INGREDIENTS, 409, "Submit requires at least one ingredient")
    if not affidavit_currency_ok(product):
        fail(ERR_AFF_MISSING, 409, "An ingredient requiring an affidavit has no current ACCEPTED affidavit")
    product["enrollment_status"] = "SUBMITTED"
    recompute_exposure(product, bump=False)
    touch(product)
    return ok(product_view(product))


@app.route("/products/<pid>/begin-evaluation", methods=["POST"])
def begin_evaluation(pid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"VerifierAdmin"})
    product = get_rec(products, pid, "Product")
    if product["enrollment_status"] != "SUBMITTED":
        fail(ERR_PRODUCT_STATE, 409, "begin-evaluation requires enrollment_status SUBMITTED")
    product["enrollment_status"] = "UNDER_EVALUATION"
    touch(product)
    return ok(product_view(product))


@app.route("/products/<pid>/decide", methods=["POST"])
def decide_product(pid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"decision", "rejection_reason"})
    decision = req_enum(data, "decision", ["VERIFIED", "REJECTED"])
    rejection_reason = None
    if decision == "REJECTED":
        rejection_reason = req_str(data, "rejection_reason", non_empty=True)
    elif "rejection_reason" in data and data["rejection_reason"] is not None:
        if not isinstance(data["rejection_reason"], str):
            fail(ERR_VALID, 400, "rejection_reason must be a string")
    require_role(role, {"VerifierAdmin"})
    product = get_rec(products, pid, "Product")
    if product["enrollment_status"] != "UNDER_EVALUATION":
        fail(ERR_PRODUCT_STATE, 409, "decide requires enrollment_status UNDER_EVALUATION")
    if decision == "REJECTED":
        product["enrollment_status"] = "REJECTED"
        product["rejection_reason"] = rejection_reason
        touch(product)
        return ok(product_view(product))
    # VERIFIED gate chain, in declared order
    ings = ingredients_of(pid)
    if any(i["compliance_status"] == "NON_COMPLIANT" for i in ings):
        fail(ERR_NON_COMPLIANT, 409, "An ingredient has compliance_status NON_COMPLIANT")
    if any(i["compliance_status"] == "PENDING" for i in ings):
        fail(ERR_PENDING, 409, "An ingredient has compliance_status PENDING")
    for plan in plans_of_product(pid):
        if plan["status"] != "CANCELLED" and plan["status"] != "COMPLETED":
            fail(ERR_INCOMPLETE_SAMPLING, 409, "A non-CANCELLED sampling plan is not COMPLETED")
    brand = brands[product["brand_id"]]
    if most_recent_passed_audit(brand["id"]) is None:
        fail(ERR_AUDIT_NOT_PASSED, 409, "No PASSED facility audit exists for the brand")
    if any(c["status"] == "OPENED" for c in cases_of_product(pid)):
        fail(ERR_OPEN_CASE, 409, "An enforcement case is OPENED for this product")
    if brand["rolling_penalty_points"] >= 10:
        fail(ERR_RECENT, 403, "Brand rolling_penalty_points >= 10")
    standard = product_standard(product)
    if not audit_fresh(standard, brand["id"]):
        fail(ERR_AUDIT_STALE, 409, "Most recent PASSED audit is stale")
    lic = license_of_product(pid)
    t = now()
    if lic is None:
        LIC_SEQ["n"] += 1
        lic = new_rec()
        lic.update({
            "product_id": pid,
            "license_code": "LIC-%06d" % LIC_SEQ["n"],
            "valid_from": t,
            "valid_until": t + timedelta(days=standard["license_term_days"]),
            "suspended_at": None,
            "suspend_reason": None,
            "status": "ACTIVE",
        })
        licenses[lic["id"]] = lic
    elif lic["status"] == "SUSPENDED" and lic["suspend_reason"] == "SCOPE_CHANGE":
        lic["status"] = "ACTIVE"
        lic["suspended_at"] = None
        lic["suspend_reason"] = None
        touch(lic)
    product["enrollment_status"] = "VERIFIED"
    touch(product)
    recompute_brand(brand)
    return ok(product_view(product))


@app.route("/products/<pid>/resubmit", methods=["POST"])
def resubmit_product(pid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"BrandRep"})
    product = get_rec(products, pid, "Product")
    check_product_ownership(product, uid)
    if product["enrollment_status"] != "REJECTED":
        fail(ERR_PRODUCT_STATE, 409, "resubmit requires enrollment_status REJECTED")
    if not affidavit_currency_ok(product):
        fail(ERR_AFF_MISSING, 409, "An ingredient requiring an affidavit has no current ACCEPTED affidavit")
    product["enrollment_status"] = "SUBMITTED"
    product["rejection_reason"] = None
    touch(product)
    return ok(product_view(product))


@app.route("/products/<pid>/renew", methods=["POST"])
def renew_product(pid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"BrandRep"})
    product = get_rec(products, pid, "Product")
    check_product_ownership(product, uid)
    if product["enrollment_status"] not in ("VERIFIED", "RENEWAL_DUE"):
        fail(ERR_PRODUCT_STATE, 409, "renew requires enrollment_status VERIFIED or RENEWAL_DUE")
    if any(c["status"] == "OPENED" for c in cases_of_product(pid)):
        fail(ERR_OPEN_CASE, 409, "An enforcement case is OPENED for this product")
    brand = brands[product["brand_id"]]
    if brand["standing_status"] != "GOOD_STANDING":
        fail(ERR_PROBATION, 403, "Brand is on probation and cannot renew")
    if brand["rolling_penalty_points"] >= 10:
        fail(ERR_RECENT, 403, "Brand rolling_penalty_points >= 10")
    if not affidavit_currency_ok(product):
        fail(ERR_AFF_MISSING, 409, "An ingredient requiring an affidavit has no current ACCEPTED affidavit")
    if most_recent_passed_audit(brand["id"]) is None:
        fail(ERR_AUDIT_NOT_PASSED, 409, "No PASSED facility audit exists for the brand")
    standard = product_standard(product)
    lic = license_of_product(pid)
    t = now()
    window_opens = lic["valid_until"] - timedelta(days=standard["renewal_window_days"])
    if not (t >= window_opens and t < lic["valid_until"]):
        fail(ERR_RENEWAL_CLOSED, 409, "Renewal window is not open")
    if not audit_fresh(standard, brand["id"]):
        fail(ERR_AUDIT_STALE, 409, "Most recent PASSED audit is stale")
    lic["valid_until"] = lic["valid_until"] + timedelta(days=standard["license_term_days"])
    touch(lic)
    product["enrollment_status"] = "VERIFIED"
    touch(product)
    return ok(product_view(product))


@app.route("/products/<pid>/reinstate", methods=["POST"])
def reinstate_product(pid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"VerifierAdmin"})
    product = get_rec(products, pid, "Product")
    if product["enrollment_status"] != "SUSPENDED":
        fail(ERR_PRODUCT_STATE, 409, "reinstate requires enrollment_status SUSPENDED")
    if any(c["status"] == "OPENED" for c in cases_of_product(pid)):
        fail(ERR_OPEN_CASE, 409, "An enforcement case is OPENED for this product")
    lic = license_of_product(pid)
    t = now()
    if lic is not None and lic["status"] == "SUSPENDED":
        if lic["suspend_reason"] == "ENFORCEMENT":
            lic["valid_until"] = lic["valid_until"] + (t - lic["suspended_at"])
        lic["status"] = "ACTIVE"
        lic["suspended_at"] = None
        lic["suspend_reason"] = None
        touch(lic)
    product["enrollment_status"] = "VERIFIED"
    touch(product)
    recompute_brand(brands[product["brand_id"]])
    return ok(product_view(product))


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------

@app.route("/ingredients", methods=["POST"])
def create_ingredient():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"product_id", "name", "crop_type", "declared_weight_pct"})
    product_id = req_str(data, "product_id")
    name = req_str(data, "name")
    crop_type = req_enum(data, "crop_type", CROP_TYPES)
    weight = req_num(data, "declared_weight_pct")
    if not (dec(weight) > 0 and dec(weight) <= 100):
        fail(ERR_VALID, 400, "declared_weight_pct must be in (0, 100]")
    require_role(role, {"BrandRep"})
    product = get_rec(products, product_id, "Product")
    if product["brand_id"] != uid:
        fail(ERR_NOT_BRAND, 403, "BrandRep does not own this product's brand")
    if product["enrollment_status"] not in ("DRAFT", "REJECTED", "UNDER_EVALUATION", "VERIFIED", "RENEWAL_DUE"):
        fail(ERR_PRODUCT_STATE, 409, "Ingredients cannot be added in the product's current state")
    current_sum = sum(dec(i["declared_weight_pct"]) for i in ingredients_of(product_id))
    if current_sum + dec(weight) > 100:
        fail(ERR_WEIGHT_SUM, 422, "Sum of declared_weight_pct would exceed 100")
    standard = product_standard(product)
    is_exempt = dec(weight) <= dec(standard["exemption_max_weight_pct"])
    requires_pcr = (crop_type == "HIGH_RISK") and (not is_exempt)
    requires_affidavit = (crop_type == "HIGH_RISK") or (crop_type == "LOW_RISK" and not is_exempt)
    rec = new_rec()
    rec.update({
        "product_id": product_id,
        "name": name,
        "crop_type": crop_type,
        "declared_weight_pct": weight,
        "is_exempt": is_exempt,
        "requires_pcr": requires_pcr,
        "requires_affidavit": requires_affidavit,
        # no samples or affidavits exist at creation time
        "compliance_status": "EXEMPTED" if (not requires_pcr and not requires_affidavit) else "PENDING",
    })
    ingredients[rec["id"]] = rec
    prior = product["enrollment_status"]
    if prior in ("VERIFIED", "RENEWAL_DUE"):
        product["enrollment_status"] = "UNDER_EVALUATION"
        touch(product)
        lic = license_of_product(product_id)
        if lic is not None and lic["status"] == "ACTIVE":
            lic["status"] = "SUSPENDED"
            lic["suspend_reason"] = "SCOPE_CHANGE"
            lic["suspended_at"] = now()
            touch(lic)
        recompute_brand(brands[product["brand_id"]])
    return ok(ingredient_view(rec), status=201)


@app.route("/ingredients", methods=["GET"])
def list_ingredients():
    auth()
    items = filter_exact(list(ingredients.values()), "product_id", request.args.get("product_id"))
    page, pagination = paginate(items)
    return ok([ingredient_view(i) for i in page], rtype="array", pagination=pagination)


@app.route("/ingredients/<iid>", methods=["GET"])
def get_ingredient(iid):
    auth()
    return ok(ingredient_view(get_rec(ingredients, iid, "Ingredient")))


# ---------------------------------------------------------------------------
# Affidavits
# ---------------------------------------------------------------------------

@app.route("/affidavits", methods=["POST"])
def create_affidavit():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"ingredient_id", "supplier_name", "valid_from", "valid_until"})
    ingredient_id = req_str(data, "ingredient_id")
    supplier_name = req_str(data, "supplier_name")
    valid_from = parse_dt(data.get("valid_from"), "valid_from") if data.get("valid_from") is not None \
        else fail(ERR_VALID, 400, "Missing required field: valid_from")
    valid_until = parse_dt(data.get("valid_until"), "valid_until") if data.get("valid_until") is not None \
        else fail(ERR_VALID, 400, "Missing required field: valid_until")
    if not valid_until > valid_from:
        fail(ERR_VALID, 400, "valid_until must be strictly later than valid_from")
    require_role(role, {"BrandRep"})
    ing = get_rec(ingredients, ingredient_id, "Ingredient")
    product = products[ing["product_id"]]
    if product["brand_id"] != uid:
        fail(ERR_NOT_BRAND, 403, "BrandRep does not own this ingredient's brand")
    for sib in affidavits_of(ingredient_id):
        if sib["supplier_name"] == supplier_name and sib["status"] in ("SUBMITTED", "ACCEPTED"):
            if valid_from < sib["valid_until"] and sib["valid_from"] < valid_until:
                fail(ERR_AFF_OVERLAP, 409, "Affidavit window overlaps an existing SUBMITTED/ACCEPTED window")
    rec = new_rec()
    rec.update({
        "ingredient_id": ingredient_id,
        "supplier_name": supplier_name,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "SUBMITTED",
        "submitted_by_user_id": uid,
    })
    affidavits[rec["id"]] = rec
    return ok(affidavit_view(rec), status=201)


@app.route("/affidavits", methods=["GET"])
def list_affidavits():
    auth()
    items = list(affidavits.values())
    items = filter_exact(items, "ingredient_id", request.args.get("ingredient_id"))
    items = filter_exact(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([affidavit_view(a) for a in page], rtype="array", pagination=pagination)


@app.route("/affidavits/<aid>", methods=["GET"])
def get_affidavit(aid):
    auth()
    return ok(affidavit_view(get_rec(affidavits, aid, "SupplierAffidavit")))


@app.route("/affidavits/<aid>/review", methods=["POST"])
def review_affidavit(aid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"decision"})
    decision = req_enum(data, "decision", ["ACCEPTED", "REJECTED"])
    require_role(role, {"VerifierAdmin"})
    rec = get_rec(affidavits, aid, "SupplierAffidavit")
    if rec["status"] != "SUBMITTED":
        fail(ERR_AFF_STATE, 409, "Only a SUBMITTED affidavit is reviewable")
    rec["status"] = decision
    touch(rec)
    if decision == "ACCEPTED":
        recompute_ingredient(ingredients[rec["ingredient_id"]])
    return ok(affidavit_view(rec))


# ---------------------------------------------------------------------------
# Sampling plans
# ---------------------------------------------------------------------------

@app.route("/sampling-plans", methods=["POST"])
def create_plan():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"product_id", "risk_point", "expected_product_version"})
    product_id = req_str(data, "product_id")
    risk_point = req_enum(data, "risk_point", RISK_POINTS)
    expected_version = req_int(data, "expected_product_version")
    require_role(role, {"VerifierAdmin"})
    product = get_rec(products, product_id, "Product")
    if expected_version != product["version"]:
        fail(ERR_STALE, 412, "expected_product_version does not match Product.version")
    if product["enrollment_status"] != "UNDER_EVALUATION":
        fail(ERR_PRODUCT_STATE, 409, "Sampling plans require the product UNDER_EVALUATION")
    required = compute_required_sample_count(product, risk_point)
    rec = new_rec()
    rec.update({
        "product_id": product_id,
        "risk_point": risk_point,
        "required_sample_count": required,
        "confirmed_sample_count": 0,
        "status": "COMPLETED" if required == 0 else "ACTIVE",
        "superseded_by_plan_id": None,
    })
    plans[rec["id"]] = rec
    for old in plans_of_product(product_id):
        if old["id"] != rec["id"] and old["status"] in ("ACTIVE", "COMPLETED"):
            old["status"] = "CANCELLED"
            old["superseded_by_plan_id"] = rec["id"]
            touch(old)
    touch(product)  # Product.version advances by 1
    return ok(plan_view(rec), status=201)


@app.route("/sampling-plans", methods=["GET"])
def list_plans():
    auth()
    items = list(plans.values())
    items = filter_exact(items, "product_id", request.args.get("product_id"))
    items = filter_exact(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([plan_view(p) for p in page], rtype="array", pagination=pagination)


@app.route("/sampling-plans/<pid>", methods=["GET"])
def get_plan(pid):
    auth()
    return ok(plan_view(get_rec(plans, pid, "SamplingPlan")))


# ---------------------------------------------------------------------------
# Test samples
# ---------------------------------------------------------------------------

@app.route("/samples", methods=["POST"])
def create_sample():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"sampling_plan_id", "ingredient_id"})
    plan_id = req_str(data, "sampling_plan_id")
    ingredient_id = req_str(data, "ingredient_id")
    require_role(role, {"LabAnalyst"})
    plan = get_rec(plans, plan_id, "SamplingPlan")
    ing = get_rec(ingredients, ingredient_id, "Ingredient")
    if plan["status"] != "ACTIVE":
        fail(ERR_PLAN_STATE, 409, "Sample collection requires plan ACTIVE")
    if ing["product_id"] != plan["product_id"]:
        fail(ERR_XREF, 409, "Sample's ingredient does not belong to the plan's product")
    if not ing["requires_pcr"]:
        fail(ERR_NOT_TESTABLE, 409, "Ingredient does not require PCR testing")
    rec = new_rec()
    rec.update({
        "sampling_plan_id": plan_id,
        "ingredient_id": ingredient_id,
        "result_gmo_pct": None,
        "outcome": None,
        "recorded_by_user_id": None,
        "confirmed_by_user_id": None,
        "status": "COLLECTED",
    })
    samples[rec["id"]] = rec
    return ok(sample_view(rec), status=201)


@app.route("/samples", methods=["GET"])
def list_samples():
    auth()
    items = list(samples.values())
    items = filter_exact(items, "sampling_plan_id", request.args.get("sampling_plan_id"))
    items = filter_exact(items, "ingredient_id", request.args.get("ingredient_id"))
    items = filter_exact(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([sample_view(s) for s in page], rtype="array", pagination=pagination)


@app.route("/samples/<sid>", methods=["GET"])
def get_sample(sid):
    auth()
    return ok(sample_view(get_rec(samples, sid, "TestSample")))


@app.route("/samples/<sid>/record-result", methods=["POST"])
def record_result(sid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"result_gmo_pct"})
    result = req_num(data, "result_gmo_pct")
    if not dec(result) >= 0:
        fail(ERR_VALID, 400, "result_gmo_pct must be >= 0")
    require_role(role, {"LabAnalyst"})
    rec = get_rec(samples, sid, "TestSample")
    if rec["status"] != "COLLECTED":
        fail(ERR_SAMPLE_STATE, 409, "record-result requires status COLLECTED")
    rec["result_gmo_pct"] = result
    rec["recorded_by_user_id"] = uid
    rec["status"] = "RESULT_RECORDED"
    touch(rec)
    return ok(sample_view(rec))


@app.route("/samples/<sid>/confirm", methods=["POST"])
def confirm_sample(sid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"LabAnalyst"})
    rec = get_rec(samples, sid, "TestSample")
    if rec["status"] != "RESULT_RECORDED":
        fail(ERR_SAMPLE_STATE, 409, "confirm requires status RESULT_RECORDED")
    plan = plans[rec["sampling_plan_id"]]
    if plan["status"] == "CANCELLED":
        fail(ERR_PLAN_STATE, 409, "Cannot confirm a sample under a CANCELLED plan")
    if uid == rec["recorded_by_user_id"]:
        fail(ERR_SOD, 403, "Confirmer must differ from the recorder")
    product = products[plan["product_id"]]
    standard = product_standard(product)
    rec["outcome"] = "COMPLIANT" if dec(rec["result_gmo_pct"]) <= dec(standard["ingredient_threshold_pct"]) \
        else "NON_COMPLIANT"
    rec["confirmed_by_user_id"] = uid
    rec["status"] = "CONFIRMED"
    touch(rec)
    plan["confirmed_sample_count"] += 1
    if plan["status"] == "ACTIVE" and plan["confirmed_sample_count"] >= plan["required_sample_count"]:
        plan["status"] = "COMPLETED"
    touch(plan)
    recompute_ingredient(ingredients[rec["ingredient_id"]])
    recompute_exposure(product)
    return ok(sample_view(rec))


@app.route("/samples/<sid>/invalidate", methods=["POST"])
def invalidate_sample(sid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, set())
    require_role(role, {"LabAnalyst", "VerifierAdmin"})
    rec = get_rec(samples, sid, "TestSample")
    if rec["status"] not in ("RESULT_RECORDED", "CONFIRMED"):
        fail(ERR_SAMPLE_STATE, 409, "invalidate requires status RESULT_RECORDED or CONFIRMED")
    was_confirmed = rec["status"] == "CONFIRMED"
    plan = plans[rec["sampling_plan_id"]]
    product = products[plan["product_id"]]
    if was_confirmed:
        rec["outcome"] = None
        plan["confirmed_sample_count"] -= 1
        if plan["status"] == "COMPLETED" and plan["confirmed_sample_count"] < plan["required_sample_count"]:
            plan["status"] = "ACTIVE"
        touch(plan)
    rec["status"] = "INVALIDATED"
    touch(rec)
    if was_confirmed:
        recompute_ingredient(ingredients[rec["ingredient_id"]])
        recompute_exposure(product)
    return ok(sample_view(rec))


# ---------------------------------------------------------------------------
# Facility audits
# ---------------------------------------------------------------------------

@app.route("/facility-audits", methods=["POST"])
def create_audit():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"brand_id", "facility_name", "auditor_id", "scheduled_date"})
    brand_id = req_str(data, "brand_id")
    facility_name = req_str(data, "facility_name")
    auditor_id = req_str(data, "auditor_id")
    if data.get("scheduled_date") is None:
        fail(ERR_VALID, 400, "Missing required field: scheduled_date")
    scheduled_date = parse_dt(data.get("scheduled_date"), "scheduled_date")
    require_role(role, {"VerifierAdmin"})
    get_rec(brands, brand_id, "Brand")
    for a in audits_of_brand(brand_id):
        if a["facility_name"] == facility_name and a["status"] in ("SCHEDULED", "REPORT_SUBMITTED"):
            fail(ERR_AUDIT_CAPACITY, 409, "An open audit already exists for this facility")
    rec = new_rec()
    rec.update({
        "brand_id": brand_id,
        "facility_name": facility_name,
        "auditor_id": auditor_id,
        "scheduled_date": scheduled_date,
        "lots": None,
        "traceability_score_pct": None,
        "decided_at": None,
        "status": "SCHEDULED",
    })
    audits[rec["id"]] = rec
    return ok(audit_view(rec), status=201)


@app.route("/facility-audits", methods=["GET"])
def list_audits():
    auth()
    items = list(audits.values())
    items = filter_exact(items, "brand_id", request.args.get("brand_id"))
    items = filter_exact(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([audit_view(a) for a in page], rtype="array", pagination=pagination)


@app.route("/facility-audits/<aid>", methods=["GET"])
def get_audit(aid):
    auth()
    return ok(audit_view(get_rec(audits, aid, "FacilityAudit")))


def validate_lots(data):
    if "lots" not in data or data["lots"] is None:
        fail(ERR_VALID, 400, "Missing required field: lots")
    lots = data["lots"]
    if not isinstance(lots, list) or len(lots) == 0:
        fail(ERR_VALID, 400, "lots must be a non-empty array")
    for lot in lots:
        if not isinstance(lot, dict):
            fail(ERR_VALID, 400, "each lot must be an object")
        for k in lot:
            if k not in ("lot_code", "input_qty", "recovered_qty"):
                fail(ERR_VALID, 400, "Unknown field in lot: %s" % k)
        if "lot_code" not in lot or not isinstance(lot["lot_code"], str):
            fail(ERR_VALID, 400, "lot_code is required and must be a string")
        for fname, cond, msg in (("input_qty", lambda v: dec(v) > 0, "input_qty must be > 0"),
                                 ("recovered_qty", lambda v: dec(v) >= 0, "recovered_qty must be >= 0")):
            if fname not in lot or isinstance(lot[fname], bool) or not isinstance(lot[fname], (int, float)):
                fail(ERR_VALID, 400, "%s is required and must be a number" % fname)
            if not cond(lot[fname]):
                fail(ERR_VALID, 400, msg)
    return lots


@app.route("/facility-audits/<aid>/submit-report", methods=["POST"])
def submit_report(aid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"lots"})
    lots = validate_lots(data)
    require_role(role, {"Auditor"})
    rec = get_rec(audits, aid, "FacilityAudit")
    if rec["status"] != "SCHEDULED":
        fail(ERR_AUDIT_STATE, 409, "submit-report requires status SCHEDULED")
    if uid != rec["auditor_id"]:
        fail(ERR_NOT_AUDITOR, 403, "Only the assigned auditor may submit the report")
    per_lot = []
    for lot in lots:
        pct = (dec(lot["recovered_qty"]) / dec(lot["input_qty"]) * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        per_lot.append(pct)
    score = (sum(per_lot) / len(per_lot)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rec["lots"] = lots
    rec["traceability_score_pct"] = score
    rec["status"] = "REPORT_SUBMITTED"
    touch(rec)
    return ok(audit_view(rec))


@app.route("/facility-audits/<aid>/decide", methods=["POST"])
def decide_audit(aid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"decision"})
    decision = req_enum(data, "decision", ["PASSED", "FAILED"])
    require_role(role, {"VerifierAdmin"})
    rec = get_rec(audits, aid, "FacilityAudit")
    if rec["status"] != "REPORT_SUBMITTED":
        fail(ERR_AUDIT_STATE, 409, "decide requires status REPORT_SUBMITTED")
    if decision == "PASSED" and rec["traceability_score_pct"] < Decimal("95.00"):
        fail(ERR_TRACE_LOW, 409, "traceability_score_pct below 95.00")
    rec["status"] = decision
    rec["decided_at"] = now()
    touch(rec)
    return ok(audit_view(rec))


# ---------------------------------------------------------------------------
# Label licenses (read-only)
# ---------------------------------------------------------------------------

@app.route("/licenses", methods=["GET"])
def list_licenses():
    auth()
    items = list(licenses.values())
    items = filter_exact(items, "product_id", request.args.get("product_id"))
    items = filter_exact(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([license_view(l) for l in page], rtype="array", pagination=pagination)


@app.route("/licenses/<lid>", methods=["GET"])
def get_license(lid):
    auth()
    return ok(license_view(get_rec(licenses, lid, "LabelLicense")))


# ---------------------------------------------------------------------------
# Enforcement cases
# ---------------------------------------------------------------------------

@app.route("/enforcement-cases", methods=["POST"])
def create_case():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"product_id", "source", "description"})
    product_id = req_str(data, "product_id")
    source = req_enum(data, "source", SOURCES)
    description = req_str(data, "description")
    require_role(role, {"EnforcementOfficer"})
    get_rec(products, product_id, "Product")
    rec = new_rec()
    rec.update({
        "product_id": product_id,
        "source": source,
        "description": description,
        "opened_by_user_id": uid,
        "resolved_by_user_id": None,
        "sanction": None,
        "penalty_points": 0,
        "substantiated_at": None,
        "status": "OPENED",
    })
    cases[rec["id"]] = rec
    return ok(case_view(rec), status=201)


@app.route("/enforcement-cases", methods=["GET"])
def list_cases():
    auth()
    items = list(cases.values())
    items = filter_exact(items, "product_id", request.args.get("product_id"))
    items = filter_exact(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([case_view(c) for c in page], rtype="array", pagination=pagination)


@app.route("/enforcement-cases/<cid>", methods=["GET"])
def get_case(cid):
    auth()
    return ok(case_view(get_rec(cases, cid, "EnforcementCase")))


@app.route("/enforcement-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"outcome", "sanction"})
    outcome = req_enum(data, "outcome", ["DISMISSED", "SUBSTANTIATED"])
    sanction = None
    if outcome == "SUBSTANTIATED":
        sanction = req_enum(data, "sanction", SANCTIONS)
    else:
        if "sanction" in data and data["sanction"] is not None:
            fail(ERR_VALID, 400, "sanction must be absent for DISMISSED")
    require_role(role, {"EnforcementOfficer"})
    rec = get_rec(cases, cid, "EnforcementCase")
    if rec["status"] != "OPENED":
        fail(ERR_CASE_STATE, 409, "resolve requires status OPENED")
    if uid == rec["opened_by_user_id"]:
        fail(ERR_SOD, 403, "Resolver must differ from the opener")
    t = now()
    rec["resolved_by_user_id"] = uid
    if outcome == "DISMISSED":
        rec["status"] = "DISMISSED"
        touch(rec)
        return ok(case_view(rec))
    rec["status"] = "SUBSTANTIATED"
    rec["sanction"] = sanction
    rec["penalty_points"] = PENALTY[sanction]
    rec["substantiated_at"] = t
    touch(rec)
    product = products[rec["product_id"]]
    brand = brands[product["brand_id"]]
    lic = license_of_product(product["id"])
    if sanction == "LICENSE_SUSPENSION":
        if lic is not None:
            if lic["status"] == "ACTIVE":
                lic["status"] = "SUSPENDED"
                lic["suspend_reason"] = "ENFORCEMENT"
                lic["suspended_at"] = t
                touch(lic)
            elif lic["status"] == "SUSPENDED":
                lic["suspend_reason"] = "ENFORCEMENT"
                lic["suspended_at"] = t
                touch(lic)
        if product["enrollment_status"] in ("VERIFIED", "RENEWAL_DUE"):
            product["enrollment_status"] = "SUSPENDED"
            touch(product)
    elif sanction == "LICENSE_REVOCATION":
        if lic is not None and lic["status"] in ("ACTIVE", "SUSPENDED"):
            lic["status"] = "REVOKED"
            touch(lic)
        if product["enrollment_status"] in ("VERIFIED", "RENEWAL_DUE", "SUSPENDED"):
            product["enrollment_status"] = "REVOKED"
            touch(product)
    recompute_brand(brand)
    return ok(case_view(rec))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = auth()
    data = get_body()
    check_allowed(data, {"to_iso8601"})
    if data.get("to_iso8601") is None:
        fail(ERR_VALID, 400, "Missing required field: to_iso8601")
    new_now = parse_dt(data.get("to_iso8601"), "to_iso8601")
    require_role(role, {"VerifierAdmin"})
    CLOCK["now"] = new_now
    t = now()
    # Sweep 1: ACCEPTED affidavits past valid_until -> EXPIRED
    affected_ings = set()
    for a in affidavits.values():
        if a["status"] == "ACCEPTED" and a["valid_until"] <= t:
            a["status"] = "EXPIRED"
            touch(a)
            affected_ings.add(a["ingredient_id"])
    for iid in affected_ings:
        recompute_ingredient(ingredients[iid])
    # Sweep 2: ACTIVE licenses past valid_until -> EXPIRED; product -> LAPSED
    for lic in licenses.values():
        if lic["status"] == "ACTIVE" and lic["valid_until"] <= t:
            lic["status"] = "EXPIRED"
            touch(lic)
            product = products.get(lic["product_id"])
            if product is not None and product["enrollment_status"] in ("VERIFIED", "RENEWAL_DUE"):
                product["enrollment_status"] = "LAPSED"
                touch(product)
                recompute_brand(brands[product["brand_id"]])
    # Sweep 3: VERIFIED products entering the renewal window -> RENEWAL_DUE
    for product in products.values():
        if product["enrollment_status"] != "VERIFIED":
            continue
        lic = license_of_product(product["id"])
        if lic is None or lic["status"] != "ACTIVE":
            continue
        standard = product_standard(product)
        window_opens = lic["valid_until"] - timedelta(days=standard["renewal_window_days"])
        if window_opens <= t < lic["valid_until"]:
            product["enrollment_status"] = "RENEWAL_DUE"
            touch(product)
    # Sweep 4: rolling penalty windows re-evaluated for every brand
    for brand in brands.values():
        recompute_brand(brand)
    return ok({"current_utc": fmt_dt(t)})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
