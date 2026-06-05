import os
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# In-memory store
# =============================================================================


class DB:
    def __init__(self):
        self.plans = {}
        self.drugs = {}
        self.protocols = {}
        self.members = {}
        self.prior_auths = {}
        self.claims = {}
        self.copay_cards = {}
        self.rebate_agreements = {}
        self.rebate_accruals = {}
        # Logical server clock; default 1970-01-01T00:00:00.000Z
        self.clock = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


db = DB()

VALID_ROLES = {"PlanAdmin", "PharmacistReviewer", "MedicalDirector", "PharmacyProvider"}


# =============================================================================
# Helpers: time, ids
# =============================================================================


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# Errors
# =============================================================================


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# =============================================================================
# Response envelope
# =============================================================================


def meta_block(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": meta_block(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body), 422


# =============================================================================
# Auth
# =============================================================================


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID or X-User-Role header.")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_role(*allowed):
    uid, role = authenticate()
    if role not in allowed:
        raise err("ERR_FORBIDDEN", 403, "Role not permitted for this operation.")
    return uid, role


def require_auth_any():
    return authenticate()


# =============================================================================
# Body / param helpers
# =============================================================================


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object.")
    return data


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}.")
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be a non-empty string.")
    return v


def require_int(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}.")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be an integer.")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be an integer.")
    return v


def require_number(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", 422, f"Missing required field: {field}.")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be a number.")
    return v


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be a number.")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be a boolean.")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", 422, f"Field {field} must be a string.")
    return v


def round_half_up(value):
    """Round a numeric value to a whole integer using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Pagination
# =============================================================================


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", 422, "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", 422, "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, pag


def sorted_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


# =============================================================================
# Common-field / mutation helpers
# =============================================================================


def stamp_create(rec, versioned=True):
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a versioned resource as mutated: bump version + updated_at."""
    if "version" in rec:
        rec["version"] += 1
    rec["updated_at"] = now_iso()


# =============================================================================
# Serializers (output projections — exclude internal-only fields)
# =============================================================================


def ser_plan(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "plan_year": p["plan_year"],
        "deductible_cents": p["deductible_cents"],
        "oop_max_cents": p["oop_max_cents"],
        "tier_copay_cents": p["tier_copay_cents"],
        "mail_order_copay_multiplier": p["mail_order_copay_multiplier"],
        "specialty_requires_specialty_pharmacy": p["specialty_requires_specialty_pharmacy"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_drug(d):
    return {
        "id": d["id"],
        "plan_id": d["plan_id"],
        "ndc": d["ndc"],
        "drug_name": d["drug_name"],
        "tier": d["tier"],
        "ingredient_cost_cents": d["ingredient_cost_cents"],
        "is_specialty": d["is_specialty"],
        "pa_required": d["pa_required"],
        "step_therapy_protocol_id": d["step_therapy_protocol_id"],
        "rebate_per_fill_cents": d["rebate_per_fill_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_protocol(p):
    return {
        "id": p["id"],
        "plan_id": p["plan_id"],
        "name": p["name"],
        "first_line_ndcs": p["first_line_ndcs"],
        "created_at": p["created_at"],
    }


def ser_member(m):
    return {
        "id": m["id"],
        "plan_id": m["plan_id"],
        "full_name": m["full_name"],
        "deductible_met_cents": m["deductible_met_cents"],
        "oop_met_cents": m["oop_met_cents"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_pa(pa):
    return {
        "id": pa["id"],
        "member_id": pa["member_id"],
        "formulary_drug_id": pa["formulary_drug_id"],
        "submitted_by_user_id": pa["submitted_by_user_id"],
        "decided_by_user_id": pa["decided_by_user_id"],
        "overrides_step_therapy": pa["overrides_step_therapy"],
        "status": pa["status"],
        "approved_quantity_remaining": pa["approved_quantity_remaining"],
        "authorized_fills": pa["authorized_fills"],
        "valid_through_date": pa["valid_through_date"],
        "created_at": pa["created_at"],
        "updated_at": pa["updated_at"],
        "version": pa["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "formulary_drug_id": c["formulary_drug_id"],
        "copay_card_id": c["copay_card_id"],
        "days_supply": c["days_supply"],
        "pharmacy_type": c["pharmacy_type"],
        "prior_auth_id": c["prior_auth_id"],
        "fill_date": c["fill_date"],
        "supply_end_date": c["supply_end_date"],
        "gross_cost_cents": c["gross_cost_cents"],
        "member_pay_cents": c["member_pay_cents"],
        "copay_card_paid_cents": c["copay_card_paid_cents"],
        "plan_paid_cents": c["plan_paid_cents"],
        "adjudication_status": c["adjudication_status"],
        "rebate_status": c["rebate_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_card(c):
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "formulary_drug_id": c["formulary_drug_id"],
        "max_benefit_cents": c["max_benefit_cents"],
        "benefit_used_cents": c["benefit_used_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_agreement(a):
    return {
        "id": a["id"],
        "plan_id": a["plan_id"],
        "manufacturer_name": a["manufacturer_name"],
        "clawback_pct": a["clawback_pct"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_accrual(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "rebate_agreement_id": a["rebate_agreement_id"],
        "accrued_cents": a["accrued_cents"],
        "clawback_cents": a["clawback_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# =============================================================================
# Lookup helpers
# =============================================================================


def find(store, rid):
    return store.get(rid)


def must_find(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
    return rec


# =============================================================================
# BenefitPlan endpoints
# =============================================================================


@app.route("/pbm/plans", methods=["POST"])
def create_plan():
    require_role("PlanAdmin")
    body = get_body()

    name = require_str(body, "name")
    plan_year = require_int(body, "plan_year")
    deductible_cents = require_int(body, "deductible_cents")
    oop_max_cents = require_int(body, "oop_max_cents")

    if "tier_copay_cents" not in body or body["tier_copay_cents"] is None:
        raise err("ERR_INVALID_REQUEST", 422, "Missing required field: tier_copay_cents.")
    tier_copay = body["tier_copay_cents"]
    if not isinstance(tier_copay, dict):
        raise err("ERR_INVALID_REQUEST", 422, "tier_copay_cents must be an object.")
    required_keys = {"TIER_1", "TIER_2", "TIER_3", "SPECIALTY"}
    if set(tier_copay.keys()) != required_keys:
        raise err("ERR_INVALID_REQUEST", 422,
                  "tier_copay_cents must contain exactly TIER_1, TIER_2, TIER_3, SPECIALTY.")
    for k in required_keys:
        v = tier_copay[k]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err("ERR_INVALID_REQUEST", 422, f"tier_copay_cents[{k}] must be an integer >= 0.")

    multiplier = opt_number(body, "mail_order_copay_multiplier", 2.0)
    if multiplier <= 0:
        raise err("ERR_INVALID_REQUEST", 422, "mail_order_copay_multiplier must be > 0.")

    specialty_req = opt_bool(body, "specialty_requires_specialty_pharmacy", True)

    if deductible_cents < 0:
        raise err("ERR_INVALID_REQUEST", 422, "deductible_cents must be >= 0.")
    if oop_max_cents < deductible_cents:
        raise err("ERR_INVALID_REQUEST", 422, "oop_max_cents must be >= deductible_cents.")

    rec = {
        "name": name,
        "plan_year": plan_year,
        "deductible_cents": deductible_cents,
        "oop_max_cents": oop_max_cents,
        "tier_copay_cents": dict(tier_copay),
        "mail_order_copay_multiplier": multiplier,
        "specialty_requires_specialty_pharmacy": specialty_req,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.plans[rec["id"]] = rec
    return success(ser_plan(rec), "object", 201)


@app.route("/pbm/plans/<rid>", methods=["GET"])
def get_plan(rid):
    require_auth_any()
    rec = must_find(db.plans, rid)
    return success(ser_plan(rec), "object", 200)


@app.route("/pbm/plans", methods=["GET"])
def list_plans():
    require_auth_any()
    items = list(db.plans.values())
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_plan(p) for p in page], "array", 200, pag)


@app.route("/pbm/plans/<rid>/archive", methods=["POST"])
def archive_plan(rid):
    require_role("PlanAdmin")
    rec = must_find(db.plans, rid)
    rec["status"] = "ARCHIVED"
    touch(rec)
    return success(ser_plan(rec), "object", 200)


@app.route("/pbm/plans/<rid>/finalize-rebates", methods=["POST"])
def finalize_rebates(rid):
    require_role("PlanAdmin")
    plan = must_find(db.plans, rid)
    body = get_body()
    expected = require_int(body, "expected_benefit_plan_version")
    if expected != plan["version"]:
        raise err("ERR_STALE_VERSION", 412, "Plan version mismatch.")

    finalized_ids = []
    # Accruals for PROVISIONAL state whose claim is PAID and under this plan.
    accruals = sorted_by_created(list(db.rebate_accruals.values()))
    for acc in accruals:
        if acc["status"] != "PROVISIONAL":
            continue
        claim = db.claims.get(acc["claim_id"])
        if claim is None or claim["adjudication_status"] != "PAID":
            continue
        member = db.members.get(claim["member_id"])
        if member is None or member["plan_id"] != rid:
            continue
        acc["status"] = "FINALIZED"
        touch(acc)
        finalized_ids.append(acc["id"])

    touch(plan)
    return success(
        {"finalized_count": len(finalized_ids), "finalized_accrual_ids": finalized_ids},
        "object", 200,
    )


# =============================================================================
# FormularyDrug endpoints
# =============================================================================


@app.route("/pbm/formulary-drugs", methods=["POST"])
def create_drug():
    require_role("PlanAdmin")
    body = get_body()

    plan_id = require_str(body, "plan_id")
    ndc = require_str(body, "ndc")
    drug_name = require_str(body, "drug_name")
    tier = require_str(body, "tier")
    if tier not in {"TIER_1", "TIER_2", "TIER_3", "SPECIALTY"}:
        raise err("ERR_INVALID_REQUEST", 422, "tier must be one of TIER_1, TIER_2, TIER_3, SPECIALTY.")
    ingredient_cost = require_int(body, "ingredient_cost_cents")
    if ingredient_cost <= 0:
        raise err("ERR_INVALID_REQUEST", 422, "ingredient_cost_cents must be > 0.")

    is_specialty = opt_bool(body, "is_specialty", False)
    pa_required = opt_bool(body, "pa_required", False)
    step_id = opt_str(body, "step_therapy_protocol_id", None)
    rebate_per_fill = opt_int(body, "rebate_per_fill_cents", 0)
    if rebate_per_fill < 0:
        raise err("ERR_INVALID_REQUEST", 422, "rebate_per_fill_cents must be >= 0.")

    # Existence: plan first, then step protocol.
    must_find(db.plans, plan_id)
    if step_id is not None:
        must_find(db.protocols, step_id)

    rec = {
        "plan_id": plan_id,
        "ndc": ndc,
        "drug_name": drug_name,
        "tier": tier,
        "ingredient_cost_cents": ingredient_cost,
        "is_specialty": is_specialty,
        "pa_required": pa_required,
        "step_therapy_protocol_id": step_id,
        "rebate_per_fill_cents": rebate_per_fill,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.drugs[rec["id"]] = rec
    return success(ser_drug(rec), "object", 201)


@app.route("/pbm/formulary-drugs/<rid>", methods=["GET"])
def get_drug(rid):
    require_auth_any()
    rec = must_find(db.drugs, rid)
    return success(ser_drug(rec), "object", 200)


@app.route("/pbm/formulary-drugs", methods=["GET"])
def list_drugs():
    require_auth_any()
    items = list(db.drugs.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        items = [d for d in items if d["plan_id"] == plan_id]
    step_id = request.args.get("step_therapy_protocol_id")
    if step_id:
        items = [d for d in items if d["step_therapy_protocol_id"] == step_id]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_drug(d) for d in page], "array", 200, pag)


@app.route("/pbm/formulary-drugs/<rid>/delist", methods=["POST"])
def delist_drug(rid):
    require_role("PlanAdmin")
    rec = must_find(db.drugs, rid)
    rec["status"] = "INACTIVE"
    touch(rec)
    return success(ser_drug(rec), "object", 200)


# =============================================================================
# StepTherapyProtocol endpoints
# =============================================================================


@app.route("/pbm/step-therapy-protocols", methods=["POST"])
def create_protocol():
    require_role("PlanAdmin")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    name = require_str(body, "name")
    if "first_line_ndcs" not in body or body["first_line_ndcs"] is None:
        raise err("ERR_INVALID_REQUEST", 422, "Missing required field: first_line_ndcs.")
    ndcs = body["first_line_ndcs"]
    if not isinstance(ndcs, list) or len(ndcs) == 0 or not all(isinstance(x, str) for x in ndcs):
        raise err("ERR_INVALID_REQUEST", 422, "first_line_ndcs must be a non-empty array of strings.")

    must_find(db.plans, plan_id)

    rec = {
        "plan_id": plan_id,
        "name": name,
        "first_line_ndcs": list(ndcs),
    }
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    db.protocols[rec["id"]] = rec
    return success(ser_protocol(rec), "object", 201)


@app.route("/pbm/step-therapy-protocols/<rid>", methods=["GET"])
def get_protocol(rid):
    require_auth_any()
    rec = must_find(db.protocols, rid)
    return success(ser_protocol(rec), "object", 200)


@app.route("/pbm/step-therapy-protocols", methods=["GET"])
def list_protocols():
    require_auth_any()
    items = list(db.protocols.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        items = [p for p in items if p["plan_id"] == plan_id]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_protocol(p) for p in page], "array", 200, pag)


# =============================================================================
# Member endpoints
# =============================================================================


@app.route("/pbm/members", methods=["POST"])
def create_member():
    require_role("PlanAdmin")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    full_name = require_str(body, "full_name")

    must_find(db.plans, plan_id)

    rec = {
        "plan_id": plan_id,
        "full_name": full_name,
        "deductible_met_cents": 0,
        "oop_met_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.members[rec["id"]] = rec
    return success(ser_member(rec), "object", 201)


@app.route("/pbm/members/<rid>", methods=["GET"])
def get_member(rid):
    require_auth_any()
    rec = must_find(db.members, rid)
    return success(ser_member(rec), "object", 200)


@app.route("/pbm/members", methods=["GET"])
def list_members():
    require_auth_any()
    items = list(db.members.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        items = [m for m in items if m["plan_id"] == plan_id]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_member(m) for m in page], "array", 200, pag)


@app.route("/pbm/members/<rid>/terminate", methods=["POST"])
def terminate_member(rid):
    require_role("PlanAdmin")
    rec = must_find(db.members, rid)
    rec["status"] = "TERMINATED"
    touch(rec)
    return success(ser_member(rec), "object", 200)


# =============================================================================
# PriorAuthorization endpoints
# =============================================================================


@app.route("/pbm/prior-authorizations", methods=["POST"])
def create_pa():
    uid, _ = require_role("PharmacistReviewer")
    body = get_body()
    member_id = require_str(body, "member_id")
    drug_id = require_str(body, "formulary_drug_id")
    authorized_fills = require_int(body, "authorized_fills")
    if authorized_fills < 1:
        raise err("ERR_INVALID_REQUEST", 422, "authorized_fills must be >= 1.")
    valid_through = require_str(body, "valid_through_date")
    if parse_iso(valid_through) is None:
        raise err("ERR_INVALID_REQUEST", 422, "valid_through_date must be a valid ISO 8601 datetime.")
    overrides_step = opt_bool(body, "overrides_step_therapy", False)

    # Existence: member then drug.
    must_find(db.members, member_id)
    must_find(db.drugs, drug_id)

    rec = {
        "member_id": member_id,
        "formulary_drug_id": drug_id,
        "submitted_by_user_id": uid,
        "decided_by_user_id": None,
        "overrides_step_therapy": overrides_step,
        "status": "PENDING_REVIEW",
        "approved_quantity_remaining": 0,
        "authorized_fills": authorized_fills,
        "valid_through_date": valid_through,
    }
    stamp_create(rec)
    db.prior_auths[rec["id"]] = rec
    return success(ser_pa(rec), "object", 201)


@app.route("/pbm/prior-authorizations/<rid>", methods=["GET"])
def get_pa(rid):
    require_auth_any()
    rec = must_find(db.prior_auths, rid)
    return success(ser_pa(rec), "object", 200)


@app.route("/pbm/prior-authorizations", methods=["GET"])
def list_pas():
    require_auth_any()
    items = list(db.prior_auths.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [p for p in items if p["member_id"] == member_id]
    drug_id = request.args.get("formulary_drug_id")
    if drug_id:
        items = [p for p in items if p["formulary_drug_id"] == drug_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_pa(p) for p in page], "array", 200, pag)


@app.route("/pbm/prior-authorizations/<rid>/decide", methods=["POST"])
def decide_pa(rid):
    uid, _ = require_role("MedicalDirector")
    pa = must_find(db.prior_auths, rid)
    body = get_body()

    decision = body.get("decision")
    if decision not in {"APPROVE", "DENY"}:
        raise err("ERR_INVALID_REQUEST", 422, "decision must be APPROVE or DENY.")
    if "expected_prior_authorization_version" not in body or body["expected_prior_authorization_version"] is None:
        raise err("ERR_INVALID_REQUEST", 422, "Missing required field: expected_prior_authorization_version.")
    expected = body["expected_prior_authorization_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", 422, "expected_prior_authorization_version must be an integer.")

    # Order: state legality, then segregation of duties, then version.
    if pa["status"] not in {"PENDING_REVIEW", "APPEALED"}:
        raise err("ERR_INVALID_STATE", 409, "PA is not in a decidable state.")
    if uid == pa["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403,
                  "The deciding user may not be the submitter.")
    if expected != pa["version"]:
        raise err("ERR_STALE_VERSION", 412, "PA version mismatch.")

    if decision == "APPROVE":
        pa["status"] = "APPROVED"
        pa["decided_by_user_id"] = uid
        pa["approved_quantity_remaining"] = pa["authorized_fills"]
    else:
        pa["status"] = "DENIED"
        pa["decided_by_user_id"] = uid
    touch(pa)
    return success(ser_pa(pa), "object", 200)


@app.route("/pbm/prior-authorizations/<rid>/appeal", methods=["POST"])
def appeal_pa(rid):
    require_role("PharmacistReviewer")
    pa = must_find(db.prior_auths, rid)
    if pa["status"] != "DENIED":
        raise err("ERR_INVALID_STATE", 409, "Only a DENIED PA can be appealed.")
    pa["status"] = "APPEALED"
    pa["decided_by_user_id"] = None
    touch(pa)
    return success(ser_pa(pa), "object", 200)


# =============================================================================
# Accumulator recomputation
# =============================================================================


def recompute_member_accumulators(member):
    """Replay the member's PAID claims chronologically to rebuild accumulators."""
    plan = db.plans.get(member["plan_id"])
    deductible_cap = plan["deductible_cents"] if plan else 0
    oop_cap = plan["oop_max_cents"] if plan else 0

    paid = [c for c in db.claims.values()
            if c["member_id"] == member["id"] and c["adjudication_status"] == "PAID"]
    paid.sort(key=lambda c: (c["created_at"], c["id"]))

    deductible_met = 0
    oop_met = 0
    for c in paid:
        rem_ded = max(0, deductible_cap - deductible_met)
        ded_portion = min(c["gross_cost_cents"], rem_ded)
        deductible_met += ded_portion

        true_oop = c["member_pay_cents"] - c["copay_card_paid_cents"]
        oop_met = min(oop_cap, oop_met + true_oop)

    changed = (member["deductible_met_cents"] != deductible_met or
               member["oop_met_cents"] != oop_met)
    member["deductible_met_cents"] = deductible_met
    member["oop_met_cents"] = oop_met
    if changed:
        touch(member)


def recompute_card_benefit(card, exclude_claim_id=None):
    """Recompute a copay card's used benefit from PAID claims that drew on it."""
    used = 0
    for c in db.claims.values():
        if c["copay_card_id"] != card["id"]:
            continue
        if c["adjudication_status"] != "PAID":
            continue
        if exclude_claim_id is not None and c["id"] == exclude_claim_id:
            continue
        used += c["copay_card_paid_cents"]

    new_status = "EXHAUSTED" if used >= card["max_benefit_cents"] else "ACTIVE"
    changed = (card["benefit_used_cents"] != used or card["status"] != new_status)
    card["benefit_used_cents"] = used
    card["status"] = new_status
    if changed:
        touch(card)


# =============================================================================
# Step therapy
# =============================================================================


def step_satisfied(member_id, drug, prior_auth):
    protocol = db.protocols.get(drug["step_therapy_protocol_id"])
    if protocol is None:
        return True
    if (prior_auth is not None and prior_auth["status"] == "APPROVED"
            and prior_auth["overrides_step_therapy"]):
        return True
    first_line = set(protocol["first_line_ndcs"])
    for c in db.claims.values():
        if c["member_id"] != member_id:
            continue
        if c["adjudication_status"] != "PAID":
            continue
        cdrug = db.drugs.get(c["formulary_drug_id"])
        if cdrug is not None and cdrug["ndc"] in first_line:
            return True
    return False


# =============================================================================
# Claim endpoints
# =============================================================================


@app.route("/pbm/claims", methods=["POST"])
def create_claim():
    require_role("PharmacyProvider")
    body = get_body()

    member_id = require_str(body, "member_id")
    drug_id = require_str(body, "formulary_drug_id")
    days_supply = require_int(body, "days_supply")
    pharmacy_type = require_str(body, "pharmacy_type")
    if pharmacy_type not in {"RETAIL", "MAIL_ORDER", "SPECIALTY"}:
        raise err("ERR_INVALID_REQUEST", 422, "pharmacy_type invalid.")
    prior_auth_id = opt_str(body, "prior_auth_id", None)
    copay_card_id = opt_str(body, "copay_card_id", None)

    # ---- Existence (left-to-right: member, drug, plan, PA, copay_card) ----
    member = must_find(db.members, member_id)
    drug = must_find(db.drugs, drug_id)
    plan = must_find(db.plans, member["plan_id"])
    prior_auth = None
    if prior_auth_id is not None:
        prior_auth = must_find(db.prior_auths, prior_auth_id)
    copay_card = None
    if copay_card_id is not None:
        copay_card = must_find(db.copay_cards, copay_card_id)

    # Build the claim record now (REJECTED claims persist as audit records).
    fill_dt = db.clock
    rec = {
        "member_id": member_id,
        "formulary_drug_id": drug_id,
        "copay_card_id": copay_card_id,
        "days_supply": days_supply,
        "pharmacy_type": pharmacy_type,
        "prior_auth_id": prior_auth_id,
        "fill_date": fmt_dt(fill_dt),
        "supply_end_date": None,
        "gross_cost_cents": 0,
        "member_pay_cents": 0,
        "copay_card_paid_cents": 0,
        "plan_paid_cents": 0,
        "adjudication_status": "SUBMITTED",
        "rebate_status": "NONE",
    }
    stamp_create(rec)

    try:
        _adjudicate(rec, member, drug, plan, prior_auth, copay_card, fill_dt, days_supply)
    except ApiError:
        # Business-rule failure: the claim is "rejected with ERR_X" — return the
        # error envelope (per §5 error catalogue / §3.4 "rejected with ERR_X"),
        # while still persisting the REJECTED claim as a terminal audit record
        # with no side effects fired.
        rec["adjudication_status"] = "REJECTED"
        rec["supply_end_date"] = None
        db.claims[rec["id"]] = rec
        raise

    db.claims[rec["id"]] = rec
    return success(ser_claim(rec), "object", 201)


def _adjudicate(rec, member, drug, plan, prior_auth, copay_card, fill_dt, days_supply):
    """Run the gatekeeping checks in priority order; raise ApiError on failure.
    On success, mutate rec into PAID and fire all side effects."""

    # Priority 6: lifecycle resources active.
    if member["status"] != "ACTIVE" or drug["status"] != "ACTIVE" or plan["status"] != "ACTIVE":
        raise err("ERR_INACTIVE_RESOURCE", 409, "Member, drug, or plan is not active.")

    # Priority 7: days_supply rules.
    if days_supply not in (30, 90):
        raise err("ERR_INVALID_DAYS_SUPPLY", 422, "days_supply must be 30 or 90.")
    if rec["pharmacy_type"] == "MAIL_ORDER" and days_supply != 90:
        raise err("ERR_INVALID_DAYS_SUPPLY", 422, "MAIL_ORDER requires days_supply == 90.")

    # Priority 8: specialty pharmacy channel.
    if drug["is_specialty"] and plan["specialty_requires_specialty_pharmacy"]:
        if rec["pharmacy_type"] != "SPECIALTY":
            raise err("ERR_SPECIALTY_PHARMACY_REQUIRED", 422,
                      "Specialty drug requires SPECIALTY pharmacy.")

    # Priority 9: PA gate.
    if drug["pa_required"]:
        if (prior_auth is None
                or prior_auth["status"] != "APPROVED"
                or prior_auth["member_id"] != member["id"]
                or prior_auth["formulary_drug_id"] != drug["id"]
                or prior_auth["approved_quantity_remaining"] < 1):
            raise err("ERR_PA_REQUIRED", 422, "An APPROVED PA with remaining fills is required.")

    # Priority 10: PA validity window (when a PA is referenced).
    if prior_auth is not None:
        vtd = parse_iso(prior_auth["valid_through_date"])
        if vtd is not None and not (fill_dt < vtd):
            raise err("ERR_PA_WINDOW_EXPIRED", 422, "Claim fill_date is at/after PA valid_through_date.")

    # Priority 11: step therapy.
    if drug["step_therapy_protocol_id"] is not None:
        if not step_satisfied(member["id"], drug, prior_auth):
            raise err("ERR_STEP_THERAPY_NOT_MET", 422, "Step therapy not satisfied.")

    # Priority 12: refill-too-soon.
    for c in db.claims.values():
        if c["member_id"] != member["id"] or c["formulary_drug_id"] != drug["id"]:
            continue
        if c["adjudication_status"] != "PAID":
            continue
        sed = parse_iso(c["supply_end_date"]) if c["supply_end_date"] else None
        if sed is not None and fill_dt < sed:
            raise err("ERR_REFILL_TOO_SOON", 422, "Refill too soon.")

    # Priority 13: copay card validity.
    if copay_card is not None:
        if (copay_card["member_id"] != member["id"]
                or copay_card["formulary_drug_id"] != drug["id"]
                or copay_card["status"] != "ACTIVE"):
            raise err("ERR_COPAY_CARD_INVALID", 422, "Copay card invalid for this claim.")

    # ---- All gates pass: PAY ----
    supply_end = fill_dt + timedelta(days=days_supply)
    rec["supply_end_date"] = fmt_dt(supply_end)

    # calc_gross_cost
    gross = drug["ingredient_cost_cents"] * (1 if days_supply == 30 else 3)
    rec["gross_cost_cents"] = gross

    # calc_member_pay
    remaining_deductible = max(0, plan["deductible_cents"] - member["deductible_met_cents"])
    remaining_oop = max(0, plan["oop_max_cents"] - member["oop_met_cents"])

    ded_portion = min(gross, remaining_deductible)
    post_ded = gross - ded_portion

    base_copay = plan["tier_copay_cents"][drug["tier"]]
    if rec["pharmacy_type"] == "MAIL_ORDER":
        copay = round_half_up(Decimal(str(base_copay)) * Decimal(str(plan["mail_order_copay_multiplier"])))
    else:
        copay = base_copay
    copay_portion = min(copay, post_ded)

    member_pay_uncapped = ded_portion + copay_portion
    member_pay = min(member_pay_uncapped, remaining_oop)
    rec["member_pay_cents"] = member_pay

    # calc_copay_card_draw
    if copay_card is None:
        card_draw = 0
    else:
        card_remaining = copay_card["max_benefit_cents"] - copay_card["benefit_used_cents"]
        card_draw = min(member_pay, card_remaining)
    rec["copay_card_paid_cents"] = card_draw

    rec["plan_paid_cents"] = gross - member_pay

    rec["adjudication_status"] = "PAID"

    # Register claim into store BEFORE recompute so replays see it.
    db.claims[rec["id"]] = rec

    # Recompute member accumulators (includes this new PAID claim).
    recompute_member_accumulators(member)

    # Copay card: recompute used benefit + status.
    if copay_card is not None:
        recompute_card_benefit(copay_card)

    # Consume PA fill; auto-EXPIRE at 0.
    if prior_auth is not None:
        prior_auth["approved_quantity_remaining"] -= 1
        if prior_auth["approved_quantity_remaining"] <= 0:
            prior_auth["status"] = "EXPIRED"
        touch(prior_auth)

    # Rebate accrual.
    if drug["rebate_per_fill_cents"] > 0:
        agreement = _find_plan_rebate_agreement(plan["id"])
        if agreement is not None:
            fills_equiv = 1 if days_supply == 30 else 3
            accrued = drug["rebate_per_fill_cents"] * fills_equiv
            acc = {
                "claim_id": rec["id"],
                "rebate_agreement_id": agreement["id"],
                "accrued_cents": accrued,
                "clawback_cents": 0,
                "status": "PROVISIONAL",
            }
            stamp_create(acc)
            db.rebate_accruals[acc["id"]] = acc
            rec["rebate_status"] = "ACCRUED"


def _find_plan_rebate_agreement(plan_id):
    candidates = [a for a in db.rebate_agreements.values() if a["plan_id"] == plan_id]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["created_at"], a["id"]))
    return candidates[0]


@app.route("/pbm/claims/<rid>", methods=["GET"])
def get_claim(rid):
    require_auth_any()
    rec = must_find(db.claims, rid)
    return success(ser_claim(rec), "object", 200)


@app.route("/pbm/claims", methods=["GET"])
def list_claims():
    require_auth_any()
    items = list(db.claims.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [c for c in items if c["member_id"] == member_id]
    drug_id = request.args.get("formulary_drug_id")
    if drug_id:
        items = [c for c in items if c["formulary_drug_id"] == drug_id]
    card_id = request.args.get("copay_card_id")
    if card_id:
        items = [c for c in items if c["copay_card_id"] == card_id]
    pa_id = request.args.get("prior_auth_id")
    if pa_id:
        items = [c for c in items if c["prior_auth_id"] == pa_id]
    status = request.args.get("adjudication_status")
    if status:
        items = [c for c in items if c["adjudication_status"] == status]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_claim(c) for c in page], "array", 200, pag)


@app.route("/pbm/claims/<rid>/reverse", methods=["POST"])
def reverse_claim(rid):
    require_role("PharmacyProvider")
    claim = must_find(db.claims, rid)
    if claim["adjudication_status"] != "PAID":
        raise err("ERR_INVALID_STATE", 409, "Only a PAID claim can be reversed.")

    member = db.members.get(claim["member_id"])

    # Flip to REVERSED first so recomputes exclude it.
    claim["adjudication_status"] = "REVERSED"

    # Recompute member accumulators excluding this claim.
    if member is not None:
        recompute_member_accumulators(member)

    # Copay card restore.
    if claim["copay_card_id"] is not None:
        card = db.copay_cards.get(claim["copay_card_id"])
        if card is not None:
            recompute_card_benefit(card)

    # Restore PA fill.
    if claim["prior_auth_id"] is not None:
        pa = db.prior_auths.get(claim["prior_auth_id"])
        if pa is not None and pa["status"] != "EXPIRED":
            pa["approved_quantity_remaining"] += 1
            touch(pa)

    # Rebate unwind.
    accrual = None
    for a in db.rebate_accruals.values():
        if a["claim_id"] == claim["id"]:
            accrual = a
            break
    if accrual is not None:
        if accrual["status"] == "PROVISIONAL":
            del db.rebate_accruals[accrual["id"]]
            claim["rebate_status"] = "NONE"
        elif accrual["status"] == "FINALIZED":
            agreement = db.rebate_agreements.get(accrual["rebate_agreement_id"])
            clawback_pct = agreement["clawback_pct"] if agreement else 1.0
            clawback = round_half_up(
                Decimal(str(accrual["accrued_cents"])) * Decimal(str(clawback_pct)))
            accrual["clawback_cents"] = clawback
            accrual["status"] = "CLAWED_BACK"
            touch(accrual)
            claim["rebate_status"] = "CLAWED_BACK"

    touch(claim)
    return success(ser_claim(claim), "object", 200)


# =============================================================================
# CopayCard endpoints
# =============================================================================


@app.route("/pbm/copay-cards", methods=["POST"])
def create_card():
    require_role("PlanAdmin")
    body = get_body()
    member_id = require_str(body, "member_id")
    drug_id = require_str(body, "formulary_drug_id")
    max_benefit = require_int(body, "max_benefit_cents")
    if max_benefit <= 0:
        raise err("ERR_INVALID_REQUEST", 422, "max_benefit_cents must be > 0.")

    must_find(db.members, member_id)
    must_find(db.drugs, drug_id)

    rec = {
        "member_id": member_id,
        "formulary_drug_id": drug_id,
        "max_benefit_cents": max_benefit,
        "benefit_used_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.copay_cards[rec["id"]] = rec
    return success(ser_card(rec), "object", 201)


@app.route("/pbm/copay-cards/<rid>", methods=["GET"])
def get_card(rid):
    require_auth_any()
    rec = must_find(db.copay_cards, rid)
    return success(ser_card(rec), "object", 200)


@app.route("/pbm/copay-cards", methods=["GET"])
def list_cards():
    require_auth_any()
    items = list(db.copay_cards.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [c for c in items if c["member_id"] == member_id]
    drug_id = request.args.get("formulary_drug_id")
    if drug_id:
        items = [c for c in items if c["formulary_drug_id"] == drug_id]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_card(c) for c in page], "array", 200, pag)


# =============================================================================
# RebateAgreement endpoints
# =============================================================================


@app.route("/pbm/rebate-agreements", methods=["POST"])
def create_agreement():
    require_role("PlanAdmin")
    body = get_body()
    plan_id = require_str(body, "plan_id")
    manufacturer = require_str(body, "manufacturer_name")
    clawback_pct = opt_number(body, "clawback_pct", 1.0)
    if not (0 <= clawback_pct <= 1):
        raise err("ERR_INVALID_REQUEST", 422, "clawback_pct must be between 0 and 1.")

    must_find(db.plans, plan_id)

    rec = {
        "plan_id": plan_id,
        "manufacturer_name": manufacturer,
        "clawback_pct": clawback_pct,
    }
    stamp_create(rec)
    db.rebate_agreements[rec["id"]] = rec
    return success(ser_agreement(rec), "object", 201)


@app.route("/pbm/rebate-agreements/<rid>", methods=["GET"])
def get_agreement(rid):
    require_auth_any()
    rec = must_find(db.rebate_agreements, rid)
    return success(ser_agreement(rec), "object", 200)


@app.route("/pbm/rebate-agreements", methods=["GET"])
def list_agreements():
    require_auth_any()
    items = list(db.rebate_agreements.values())
    plan_id = request.args.get("plan_id")
    if plan_id:
        items = [a for a in items if a["plan_id"] == plan_id]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_agreement(a) for a in page], "array", 200, pag)


# =============================================================================
# RebateAccrual endpoints
# =============================================================================


@app.route("/pbm/rebate-accruals/<rid>", methods=["GET"])
def get_accrual(rid):
    require_auth_any()
    rec = must_find(db.rebate_accruals, rid)
    return success(ser_accrual(rec), "object", 200)


@app.route("/pbm/rebate-accruals", methods=["GET"])
def list_accruals():
    require_auth_any()
    items = list(db.rebate_accruals.values())
    claim_id = request.args.get("claim_id")
    if claim_id:
        items = [a for a in items if a["claim_id"] == claim_id]
    agreement_id = request.args.get("rebate_agreement_id")
    if agreement_id:
        items = [a for a in items if a["rebate_agreement_id"] == agreement_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    page, pag = paginate(items)
    return success([ser_accrual(a) for a in page], "array", 200, pag)


# =============================================================================
# Server clock
# =============================================================================


@app.route("/pbm/_clock/set", methods=["POST"])
def set_clock():
    require_role("PlanAdmin")
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    parsed = parse_iso(to_iso)
    if parsed is None:
        raise err("ERR_INVALID_REQUEST", 422, "to_iso8601 must be a valid ISO 8601 datetime.")
    db.clock = parsed
    return success({"current_utc": fmt_dt(parsed)}, "object", 200)


# =============================================================================
# Entry point
# =============================================================================


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
