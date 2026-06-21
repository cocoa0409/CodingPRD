"""InsurancePlan + PatientCoverage endpoints (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_COVERAGE_NOT_FOUND,
    ERR_INSURANCE_PLAN_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import (
    ROLE_BILLING,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
)
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import common

bp = Blueprint("insurance", __name__)


# ---------------------------------------------------------------------------
# Insurance Plans
# ---------------------------------------------------------------------------
@bp.post("/insurance-plans")
def create_insurance_plan():
    guard([ROLE_BILLING])
    body = common.get_json_body()
    common.require_fields(body, [
        "carrier_name", "annual_maximum_cents", "deductible_cents",
        "preventive_coinsurance_pct", "basic_coinsurance_pct", "major_coinsurance_pct",
    ])
    carrier_name = common.require_string(body, "carrier_name")
    annual_max = common.require_int(body, "annual_maximum_cents")
    if annual_max <= 0:
        raise APIError(ERR_VALIDATION, 422, "annual_maximum_cents must be > 0")
    deductible = common.require_int(body, "deductible_cents")
    if deductible < 0:
        raise APIError(ERR_VALIDATION, 422, "deductible_cents must be >= 0")

    pcts = {}
    for f in ("preventive_coinsurance_pct", "basic_coinsurance_pct", "major_coinsurance_pct"):
        v = common.require_int(body, f)
        if not (0 <= v <= 100):
            raise APIError(ERR_VALIDATION, 422, f"{f} must be 0..100")
        pcts[f] = v

    waiting = common.optional_int(body, "major_waiting_period_months", 12)
    if waiting < 0:
        raise APIError(ERR_VALIDATION, 422, "major_waiting_period_months must be >= 0")
    frequency = common.optional_int(body, "frequency_limit_months", 6)
    if frequency < 0:
        raise APIError(ERR_VALIDATION, 422, "frequency_limit_months must be >= 0")

    rec = common.new_common_fields()
    rec.update({
        "carrier_name": carrier_name,
        "annual_maximum_cents": annual_max,
        "deductible_cents": deductible,
        "preventive_coinsurance_pct": pcts["preventive_coinsurance_pct"],
        "basic_coinsurance_pct": pcts["basic_coinsurance_pct"],
        "major_coinsurance_pct": pcts["major_coinsurance_pct"],
        "major_waiting_period_months": waiting,
        "frequency_limit_months": frequency,
    })
    db.insurance_plans[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/insurance-plans/<plan_id>")
def get_insurance_plan(plan_id):
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    rec = common.resolve(db.insurance_plans, plan_id, ERR_INSURANCE_PLAN_NOT_FOUND)
    return ok_object(common.serialize(rec), 200)


# ---------------------------------------------------------------------------
# Patient Coverages
# ---------------------------------------------------------------------------
@bp.post("/patient-coverages")
def create_coverage():
    guard([ROLE_BILLING])
    body = common.get_json_body()
    common.require_fields(body, [
        "patient_id", "insurance_plan_id", "coverage_start_date", "benefit_year_start_date",
    ])
    patient_id = common.require_string(body, "patient_id")
    common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    plan_id = common.require_string(body, "insurance_plan_id")
    common.resolve(db.insurance_plans, plan_id, ERR_INSURANCE_PLAN_NOT_FOUND)
    coverage_start = common.require_string(body, "coverage_start_date")
    benefit_year_start = common.require_string(body, "benefit_year_start_date")

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient_id,
        "insurance_plan_id": plan_id,
        "coverage_start_date": coverage_start,
        "benefit_year_start_date": benefit_year_start,
        "annual_benefit_used_cents": 0,
        "deductible_met_cents": 0,
        "annual_max_reached": False,
        "status": "ACTIVE",
    })
    db.patient_coverages[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/patient-coverages")
def list_coverages():
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    records = apply_filters(list(db.patient_coverages.values()), {
        "patient_id": request.args.get("patient_id"),
        "insurance_plan_id": request.args.get("insurance_plan_id"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/patient-coverages/<coverage_id>")
def get_coverage(coverage_id):
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_PATIENT])
    rec = common.resolve(db.patient_coverages, coverage_id, ERR_COVERAGE_NOT_FOUND)
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)


@bp.post("/patient-coverages/<coverage_id>/terminate")
def terminate_coverage(coverage_id):
    guard([ROLE_BILLING])
    rec = common.resolve(db.patient_coverages, coverage_id, ERR_COVERAGE_NOT_FOUND)
    rec["status"] = "TERMINATED"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)
