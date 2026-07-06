"""Reference data + clock: clock, drug-catalog, payer-plans, nurses, pumps, patients."""
from flask import Blueprint

import errors
import helpers
from clock import clock
from db import db, stamp_create
from middleware import require
from response import object_response, array_response

bp = Blueprint("reference", __name__)

THERAPY_CATEGORIES = {"ANTI_INFECTIVE", "AMINOGLYCOSIDE_OR_VANCO", "TPN", "IMMUNE_GLOBULIN", "CHEMO"}
PUMP_MODELS = {"AMBULATORY", "STATIONARY"}
PUMP_STATUSES = {"AVAILABLE", "RETIRED"}
NURSE_STATUSES = {"ACTIVE", "INACTIVE"}

ALL_ROLES = ["IntakeCoordinator", "Pharmacist", "AuthSpecialist", "MedicalDirector",
             "Biller", "WarehouseClerk", "VisitingNurse"]


# ---------------------------------------------------------------------------
# Logical clock (no auth headers required)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = helpers.get_body()
    helpers.require_fields(body, ["to_iso8601"])
    raw = body["to_iso8601"]
    if not isinstance(raw, str):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 string")
    dt = helpers.parse_iso(raw, "to_iso8601")
    clock.set(dt)
    return object_response({"now": clock.iso()}, 200)


# ---------------------------------------------------------------------------
# DrugCatalog
# ---------------------------------------------------------------------------
@bp.route("/drug-catalog", methods=["POST"])
def create_drug():
    require(["Pharmacist"])
    body = helpers.get_body()
    ndc_code = helpers.as_str(body, "ndc_code")
    generic_name = helpers.as_str(body, "generic_name")
    therapy_category = helpers.as_enum(body, "therapy_category", THERAPY_CATEGORIES)
    vial_size_mg = helpers.as_int(body, "vial_size_mg")
    awp_per_vial_cents = helpers.as_int(body, "awp_per_vial_cents")
    is_specialty = helpers.as_bool(body, "is_specialty", default=False)
    requires_trough_lab = helpers.as_bool(body, "requires_trough_lab", default=False)
    lot_total_vials = helpers.as_int(body, "lot_total_vials")

    if vial_size_mg <= 0:
        raise errors.invalid_request("vial_size_mg must be > 0")
    if awp_per_vial_cents < 0:
        raise errors.invalid_request("awp_per_vial_cents must be >= 0")
    if lot_total_vials < 0:
        raise errors.invalid_request("lot_total_vials must be >= 0")
    if any(d["ndc_code"] == ndc_code for d in db.drug_catalog.values()):
        raise errors.invalid_request("ndc_code must be unique")

    drug = stamp_create({
        "ndc_code": ndc_code,
        "generic_name": generic_name,
        "therapy_category": therapy_category,
        "vial_size_mg": vial_size_mg,
        "awp_per_vial_cents": awp_per_vial_cents,
        "is_specialty": is_specialty,
        "requires_trough_lab": requires_trough_lab,
        "lot_total_vials": lot_total_vials,
        "on_hand_vials": lot_total_vials,
    })
    db.drug_catalog[drug["id"]] = drug
    return object_response(drug, 201)


@bp.route("/drug-catalog/<id>", methods=["GET"])
def get_drug(id):
    require(["Pharmacist", "AuthSpecialist", "MedicalDirector", "Biller", "IntakeCoordinator"])
    drug = db.drug_catalog.get(id)
    if drug is None:
        raise errors.not_found("Drug not found")
    return object_response(drug, 200)


@bp.route("/drug-catalog", methods=["GET"])
def list_drugs():
    require(["Pharmacist", "AuthSpecialist", "MedicalDirector", "Biller", "IntakeCoordinator"])
    limit, offset = helpers.pagination_params()
    items = helpers.sort_by_created(list(db.drug_catalog.values()))
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


# ---------------------------------------------------------------------------
# PayerPlan
# ---------------------------------------------------------------------------
@bp.route("/payer-plans", methods=["POST"])
def create_payer_plan():
    require(["Biller"])
    body = helpers.get_body()
    plan_code = helpers.as_str(body, "plan_code")
    per_diem = body.get("per_diem_rate_cents")
    if not isinstance(per_diem, dict):
        raise errors.invalid_request("per_diem_rate_cents must be an object")
    for k, v in per_diem.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise errors.invalid_request("per_diem_rate_cents values must be integers")
    awp_discount_pct = helpers.as_number(body, "awp_discount_pct")
    coinsurance_pct = helpers.as_number(body, "coinsurance_pct")
    deductible_remaining_cents = helpers.as_int(body, "deductible_remaining_cents")
    oop_max_remaining_cents = helpers.as_int(body, "oop_max_remaining_cents")

    if not (awp_discount_pct >= 0 and awp_discount_pct < 1):
        raise errors.invalid_request("awp_discount_pct must be >= 0 and < 1")
    if not (coinsurance_pct >= 0 and coinsurance_pct <= 1):
        raise errors.invalid_request("coinsurance_pct must be >= 0 and <= 1")
    if deductible_remaining_cents < 0:
        raise errors.invalid_request("deductible_remaining_cents must be >= 0")
    if oop_max_remaining_cents < 0:
        raise errors.invalid_request("oop_max_remaining_cents must be >= 0")
    if any(p["plan_code"] == plan_code for p in db.payer_plans.values()):
        raise errors.invalid_request("plan_code must be unique")

    plan = stamp_create({
        "plan_code": plan_code,
        "per_diem_rate_cents": dict(per_diem),
        "awp_discount_pct": awp_discount_pct,
        "coinsurance_pct": coinsurance_pct,
        "deductible_remaining_cents": deductible_remaining_cents,
        "oop_max_remaining_cents": oop_max_remaining_cents,
    })
    db.payer_plans[plan["id"]] = plan
    return object_response(plan, 201)


@bp.route("/payer-plans/<id>", methods=["GET"])
def get_payer_plan(id):
    require(["Biller", "IntakeCoordinator", "AuthSpecialist"])
    plan = db.payer_plans.get(id)
    if plan is None:
        raise errors.not_found("Payer plan not found")
    return object_response(plan, 200)


# ---------------------------------------------------------------------------
# Nurse
# ---------------------------------------------------------------------------
@bp.route("/nurses", methods=["POST"])
def create_nurse():
    require(["IntakeCoordinator"])
    body = helpers.get_body()
    full_name = helpers.as_str(body, "full_name")
    license_state = helpers.as_str(body, "license_state")
    status = helpers.as_enum(body, "status", NURSE_STATUSES, required=False, default="ACTIVE")
    if not helpers.two_upper_letters(license_state):
        raise errors.invalid_request("license_state must be two uppercase letters")

    nurse = stamp_create({
        "full_name": full_name,
        "license_state": license_state,
        "status": status,
    })
    db.nurses[nurse["id"]] = nurse
    return object_response(nurse, 201)


@bp.route("/nurses/<id>", methods=["GET"])
def get_nurse(id):
    require(["IntakeCoordinator", "VisitingNurse", "MedicalDirector"])
    nurse = db.nurses.get(id)
    if nurse is None:
        raise errors.not_found("Nurse not found")
    return object_response(nurse, 200)


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------
@bp.route("/pumps", methods=["POST"])
def create_pump():
    require(["WarehouseClerk", "Pharmacist"])
    body = helpers.get_body()
    asset_tag = helpers.as_str(body, "asset_tag")
    model = helpers.as_enum(body, "model", PUMP_MODELS)
    status = helpers.as_enum(body, "status", PUMP_STATUSES, required=False, default="AVAILABLE")
    if any(p["asset_tag"] == asset_tag for p in db.pumps.values()):
        raise errors.invalid_request("asset_tag must be unique")

    pump = stamp_create({
        "asset_tag": asset_tag,
        "model": model,
        "status": status,
    })
    db.pumps[pump["id"]] = pump
    return object_response(pump, 201)


@bp.route("/pumps/<id>", methods=["GET"])
def get_pump(id):
    require(["WarehouseClerk", "Pharmacist"])
    pump = db.pumps.get(id)
    if pump is None:
        raise errors.not_found("Pump not found")
    return object_response(pump, 200)


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------
@bp.route("/patients", methods=["POST"])
def create_patient():
    require(["IntakeCoordinator"])
    body = helpers.get_body()
    full_name = helpers.as_str(body, "full_name")
    service_state = helpers.as_str(body, "service_state")
    payer_plan_id = helpers.as_str(body, "payer_plan_id")
    # existence (3) before other body validity (4) per PRD §2.8
    if payer_plan_id not in db.payer_plans:
        raise errors.not_found("Payer plan not found")
    if not helpers.two_upper_letters(service_state):
        raise errors.invalid_request("service_state must be two uppercase letters")

    patient = stamp_create({
        "full_name": full_name,
        "service_state": service_state,
        "payer_plan_id": payer_plan_id,
        "status": "ACTIVE",
    })
    db.patients[patient["id"]] = patient
    return object_response(patient, 201)


@bp.route("/patients/<id>", methods=["GET"])
def get_patient(id):
    require(["IntakeCoordinator", "MedicalDirector", "Biller"])
    patient = db.patients.get(id)
    if patient is None:
        raise errors.not_found("Patient not found")
    return object_response(patient, 200)


@bp.route("/patients", methods=["GET"])
def list_patients():
    require(["IntakeCoordinator", "MedicalDirector", "Biller"])
    limit, offset = helpers.pagination_params()
    from flask import request
    payer_plan_id = request.args.get("payer_plan_id")
    items = list(db.patients.values())
    if payer_plan_id is not None:
        items = [p for p in items if p["payer_plan_id"] == payer_plan_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)
