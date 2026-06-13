"""Reference data: drug products, insurance plans, formulary entries,
interaction rules, prescribers (PRD §3.1)."""
from flask import Blueprint, request

import db
from common import (
    get_body, require_field, opt_field, as_string, as_bool, as_int, as_number,
    as_enum, stamp_create, touch, get_pagination, paginate,
)
from errors import err
from middleware import get_actor, require_roles
from response import object_response, array_response

bp = Blueprint("reference", __name__)

ALL_ROLES = ["PharmacyAdmin", "Pharmacist", "Technician", "Cashier"]
DEA_SCHEDULES = {"NONE", "CII", "CIII", "CIV", "CV"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}


# ===========================================================================
# DrugProduct
# ===========================================================================


def serialize_drug(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"], "ndc": d["ndc"], "name": d["name"],
        "dea_schedule": d["dea_schedule"], "unit_price_cents": d["unit_price_cents"],
        "pa_required": d["pa_required"],
        "therapeutic_substitute_of_id": d["therapeutic_substitute_of_id"],
        "is_active": d["is_active"], "status": d["status"],
    }


@bp.route("/drug-products", methods=["POST"])
def create_drug():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    body = get_body()
    ndc = as_string(require_field(body, "ndc"), "ndc")
    name = as_string(require_field(body, "name"), "name")
    dea = as_enum(opt_field(body, "dea_schedule", "NONE"), "dea_schedule", DEA_SCHEDULES)
    unit_price = as_int(require_field(body, "unit_price_cents"), "unit_price_cents", minimum=0)
    pa_required = as_bool(opt_field(body, "pa_required", False), "pa_required")
    sub_of = opt_field(body, "therapeutic_substitute_of_id", None)
    with db.LOCK:
        if sub_of is not None:
            sub_of = as_string(sub_of, "therapeutic_substitute_of_id")
            if sub_of not in db.drug_products:
                raise err("ERR_REFERENCE_NOT_FOUND",
                          "therapeutic_substitute_of_id does not reference a drug")
        if any(d["ndc"] == ndc for d in db.drug_products.values()):
            raise err("ERR_DUPLICATE_NDC", "A drug with this ndc already exists")
        drug = {
            "ndc": ndc, "name": name, "dea_schedule": dea,
            "unit_price_cents": unit_price, "pa_required": pa_required,
            "therapeutic_substitute_of_id": sub_of,
            "is_active": True, "status": "ACTIVE",
        }
        stamp_create(drug)
        db.drug_products[drug["id"]] = drug
    return object_response(serialize_drug(drug), 201)


@bp.route("/drug-products", methods=["GET"])
def list_drugs():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    sub = request.args.get("therapeutic_substitute_of_id")
    items = list(db.drug_products.values())
    if sub is not None:
        items = [d for d in items if d["therapeutic_substitute_of_id"] == sub]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_drug(d) for d in page], limit, offset, total)


@bp.route("/drug-products/<rid>", methods=["GET"])
def get_drug(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    drug = db.drug_products.get(rid)
    if drug is None:
        raise err("ERR_NOT_FOUND", "Drug product not found")
    return object_response(serialize_drug(drug), 200)


@bp.route("/drug-products/<rid>/discontinue", methods=["POST"])
def discontinue_drug(rid):
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    with db.LOCK:
        drug = db.drug_products.get(rid)
        if drug is None:
            raise err("ERR_NOT_FOUND", "Drug product not found")
        drug["status"] = "DISCONTINUED"
        drug["is_active"] = False
        touch(drug)
    return object_response(serialize_drug(drug), 200)


# ===========================================================================
# InsurancePlan
# ===========================================================================


def serialize_plan(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "bin": p["bin"], "pcn": p["pcn"], "name": p["name"],
        "copay_pct": p["copay_pct"], "copay_min_cents": p["copay_min_cents"],
        "copay_max_cents": p["copay_max_cents"],
        "dispensing_fee_cents": p["dispensing_fee_cents"],
        "refill_too_soon_threshold_pct": p["refill_too_soon_threshold_pct"],
        "requires_pa_for_controlled": p["requires_pa_for_controlled"],
    }


@bp.route("/insurance-plans", methods=["POST"])
def create_plan():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    body = get_body()
    bin_ = as_string(require_field(body, "bin"), "bin")
    pcn = as_string(require_field(body, "pcn"), "pcn")
    name = as_string(require_field(body, "name"), "name")
    copay_pct = as_number(require_field(body, "copay_pct"), "copay_pct", 0.0, 1.0)
    copay_min = as_int(opt_field(body, "copay_min_cents", 0), "copay_min_cents", minimum=0)
    copay_max = as_int(require_field(body, "copay_max_cents"), "copay_max_cents", minimum=0)
    if copay_max <= copay_min:
        raise err("ERR_INVALID_REQUEST", "copay_max_cents must exceed copay_min_cents")
    disp_fee = as_int(opt_field(body, "dispensing_fee_cents", 100), "dispensing_fee_cents", minimum=0)
    threshold = as_number(opt_field(body, "refill_too_soon_threshold_pct", 0.80),
                          "refill_too_soon_threshold_pct", 0.0, 1.0)
    req_pa_ctrl = as_bool(opt_field(body, "requires_pa_for_controlled", False),
                          "requires_pa_for_controlled")
    with db.LOCK:
        if any(p["bin"] == bin_ and p["pcn"] == pcn for p in db.insurance_plans.values()):
            raise err("ERR_DUPLICATE_PLAN_ROUTING",
                      "A plan with this bin/pcn routing already exists")
        plan = {
            "bin": bin_, "pcn": pcn, "name": name, "copay_pct": copay_pct,
            "copay_min_cents": copay_min, "copay_max_cents": copay_max,
            "dispensing_fee_cents": disp_fee,
            "refill_too_soon_threshold_pct": threshold,
            "requires_pa_for_controlled": req_pa_ctrl,
        }
        stamp_create(plan)
        db.insurance_plans[plan["id"]] = plan
    return object_response(serialize_plan(plan), 201)


@bp.route("/insurance-plans", methods=["GET"])
def list_plans():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    page, total = paginate(list(db.insurance_plans.values()), limit, offset)
    return array_response([serialize_plan(p) for p in page], limit, offset, total)


@bp.route("/insurance-plans/<rid>", methods=["GET"])
def get_plan(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    plan = db.insurance_plans.get(rid)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Insurance plan not found")
    return object_response(serialize_plan(plan), 200)


# ===========================================================================
# FormularyEntry
# ===========================================================================


def serialize_formulary(f):
    return {
        "id": f["id"], "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"], "plan_id": f["plan_id"], "drug_id": f["drug_id"],
        "tier": f["tier"], "allowed_amount_cents": f["allowed_amount_cents"],
        "requires_pa": f["requires_pa"],
    }


@bp.route("/formulary-entries", methods=["POST"])
def create_formulary():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    body = get_body()
    plan_id = as_string(require_field(body, "plan_id"), "plan_id")
    drug_id = as_string(require_field(body, "drug_id"), "drug_id")
    tier = as_int(require_field(body, "tier"), "tier", 1, 4)
    allowed = as_int(require_field(body, "allowed_amount_cents"), "allowed_amount_cents", minimum=0)
    requires_pa = as_bool(opt_field(body, "requires_pa", False), "requires_pa")
    with db.LOCK:
        if plan_id not in db.insurance_plans:
            raise err("ERR_REFERENCE_NOT_FOUND", "plan_id does not reference a plan")
        if drug_id not in db.drug_products:
            raise err("ERR_REFERENCE_NOT_FOUND", "drug_id does not reference a drug")
        entry = {
            "plan_id": plan_id, "drug_id": drug_id, "tier": tier,
            "allowed_amount_cents": allowed, "requires_pa": requires_pa,
        }
        stamp_create(entry)
        db.formulary_entries[entry["id"]] = entry
    return object_response(serialize_formulary(entry), 201)


@bp.route("/formulary-entries", methods=["GET"])
def list_formulary():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    plan_id = request.args.get("plan_id")
    drug_id = request.args.get("drug_id")
    items = list(db.formulary_entries.values())
    if plan_id is not None:
        items = [f for f in items if f["plan_id"] == plan_id]
    if drug_id is not None:
        items = [f for f in items if f["drug_id"] == drug_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_formulary(f) for f in page], limit, offset, total)


@bp.route("/formulary-entries/<rid>", methods=["GET"])
def get_formulary(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    entry = db.formulary_entries.get(rid)
    if entry is None:
        raise err("ERR_NOT_FOUND", "Formulary entry not found")
    return object_response(serialize_formulary(entry), 200)


# ===========================================================================
# InteractionRule
# ===========================================================================


def serialize_rule(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "drug_a_id": r["drug_a_id"], "drug_b_id": r["drug_b_id"],
        "severity": r["severity"], "detail": r["detail"],
    }


@bp.route("/interaction-rules", methods=["POST"])
def create_rule():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    body = get_body()
    drug_a = as_string(require_field(body, "drug_a_id"), "drug_a_id")
    drug_b = as_string(require_field(body, "drug_b_id"), "drug_b_id")
    severity = as_enum(require_field(body, "severity"), "severity", SEVERITIES)
    detail = as_string(require_field(body, "detail"), "detail")
    with db.LOCK:
        if drug_a not in db.drug_products:
            raise err("ERR_REFERENCE_NOT_FOUND", "drug_a_id does not reference a drug")
        if drug_b not in db.drug_products:
            raise err("ERR_REFERENCE_NOT_FOUND", "drug_b_id does not reference a drug")
        rule = {
            "drug_a_id": drug_a, "drug_b_id": drug_b,
            "severity": severity, "detail": detail,
        }
        stamp_create(rule)
        db.interaction_rules[rule["id"]] = rule
    return object_response(serialize_rule(rule), 201)


@bp.route("/interaction-rules", methods=["GET"])
def list_rules():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    drug_a = request.args.get("drug_a_id")
    drug_b = request.args.get("drug_b_id")
    items = list(db.interaction_rules.values())
    if drug_a is not None:
        items = [r for r in items if r["drug_a_id"] == drug_a]
    if drug_b is not None:
        items = [r for r in items if r["drug_b_id"] == drug_b]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_rule(r) for r in page], limit, offset, total)


@bp.route("/interaction-rules/<rid>", methods=["GET"])
def get_rule(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    rule = db.interaction_rules.get(rid)
    if rule is None:
        raise err("ERR_NOT_FOUND", "Interaction rule not found")
    return object_response(serialize_rule(rule), 200)


# ===========================================================================
# Prescriber
# ===========================================================================


def serialize_prescriber(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "full_name": p["full_name"], "npi": p["npi"],
        "dea_number": p["dea_number"], "dea_active": p["dea_active"],
    }


@bp.route("/prescribers", methods=["POST"])
def create_prescriber():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin"])
    body = get_body()
    full_name = as_string(require_field(body, "full_name"), "full_name")
    npi = as_string(require_field(body, "npi"), "npi")
    dea_number = opt_field(body, "dea_number", None)
    if dea_number is not None:
        dea_number = as_string(dea_number, "dea_number")
    dea_active = as_bool(opt_field(body, "dea_active", True), "dea_active")
    with db.LOCK:
        if any(p["npi"] == npi for p in db.prescribers.values()):
            raise err("ERR_DUPLICATE_NPI", "A prescriber with this npi already exists")
        prescriber = {
            "full_name": full_name, "npi": npi,
            "dea_number": dea_number, "dea_active": dea_active,
        }
        stamp_create(prescriber)
        db.prescribers[prescriber["id"]] = prescriber
    return object_response(serialize_prescriber(prescriber), 201)


@bp.route("/prescribers", methods=["GET"])
def list_prescribers():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    page, total = paginate(list(db.prescribers.values()), limit, offset)
    return array_response([serialize_prescriber(p) for p in page], limit, offset, total)


@bp.route("/prescribers/<rid>", methods=["GET"])
def get_prescriber(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    prescriber = db.prescribers.get(rid)
    if prescriber is None:
        raise err("ERR_NOT_FOUND", "Prescriber not found")
    return object_response(serialize_prescriber(prescriber), 200)
