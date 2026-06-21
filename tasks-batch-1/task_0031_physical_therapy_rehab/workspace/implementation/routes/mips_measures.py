"""MIPSQualityMeasure routes (scaffold §1.5; PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MIPS_ELIGIBILITY,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services import calculations as calc
from services.validation import (
    lookup_or_404,
    require_bool,
    require_date,
    require_enum,
    require_fields,
    require_string,
)


bp = Blueprint("mips_measures", __name__)


MEASURE_CODES = {
    "MIPS128_FALL_RISK",
    "MIPS131_PAIN_ASSESSMENT",
    "MIPS182_FUNCTIONAL_OUTCOME",
}


def _enforce_eligibility(patient: dict, therapist: dict) -> None:
    """Priority 405: MIPS eligibility — patient MEDICARE + therapist enrolled."""
    if patient["insurance_type"] != "MEDICARE":
        raise APIError(
            ERR_MIPS_ELIGIBILITY,
            422,
            "MIPS reporting requires Patient.insurance_type=MEDICARE",
        )
    if not therapist["medicare_provider_enrolled"]:
        raise APIError(
            ERR_MIPS_ELIGIBILITY,
            422,
            "MIPS reporting requires reporting therapist with medicare_provider_enrolled=true",
        )


@bp.post("/rehab/mips-measures")
def create_mips():
    require_auth(["Therapist"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "patient_id",
            "plan_of_care_id",
            "reporting_therapist_id",
            "measure_code",
            "performance_period_start",
            "performance_period_end",
            "numerator_met",
        ],
    )
    patient_id = require_string(body["patient_id"], "patient_id")
    poc_id = require_string(body["plan_of_care_id"], "plan_of_care_id")
    therapist_id = require_string(body["reporting_therapist_id"], "reporting_therapist_id")
    measure_code = require_enum(body["measure_code"], MEASURE_CODES, "measure_code")
    period_start = require_date(body["performance_period_start"], "performance_period_start")
    period_end = require_date(body["performance_period_end"], "performance_period_end")
    numerator_met = require_bool(body["numerator_met"], "numerator_met")

    patient = lookup_or_404(db.patients, patient_id, "Patient")
    poc = lookup_or_404(db.plans_of_care, poc_id, "PlanOfCare")
    therapist = lookup_or_404(db.therapists, therapist_id, "Therapist")

    # priority 405 (business-safety)
    _enforce_eligibility(patient, therapist)

    if period_end <= period_start:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "performance_period_end must be strictly after performance_period_start",
        )

    with db.mutation_lock:
        measure = {
            "patient_id": patient_id,
            "plan_of_care_id": poc_id,
            "reporting_therapist_id": therapist_id,
            "measure_code": measure_code,
            "performance_period_start": period_start.isoformat(),
            "performance_period_end": period_end.isoformat(),
            "numerator_met": numerator_met,
            "composite_score": None,
            "status": "DRAFT",
        }
        db.stamp_common(measure)
        db.mips_measures[measure["id"]] = measure
        return ok_object(measure, 201)


@bp.get("/rehab/mips-measures/<mid>")
def get_mips(mid: str):
    require_auth(["PlatformAdmin", "Therapist"])()
    measure = lookup_or_404(db.mips_measures, mid, "MIPSQualityMeasure")
    return ok_object(measure, 200)


@bp.get("/rehab/mips-measures")
def list_mips():
    require_auth(["PlatformAdmin", "Therapist"])()
    limit, offset = paginate_params(request.args)
    items = list(db.mips_measures.values())
    for key in ("patient_id", "plan_of_care_id", "reporting_therapist_id", "status"):
        if key in request.args:
            items = [m for m in items if m.get(key) == request.args.get(key)]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/rehab/mips-measures/<mid>/revise")
def revise_mips(mid: str):
    require_auth(["Therapist"])()
    measure = lookup_or_404(db.mips_measures, mid, "MIPSQualityMeasure")
    if measure["status"] != "DRAFT":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"MIPSQualityMeasure must be DRAFT to revise; current={measure['status']}",
        )
    body = get_json_body()
    new_numerator = body.get("numerator_met", measure["numerator_met"])
    new_code = body.get("measure_code", measure["measure_code"])
    if not isinstance(new_numerator, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "numerator_met must be a boolean")
    if new_code not in MEASURE_CODES:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Invalid measure_code: {new_code!r}")

    with db.mutation_lock:
        measure["numerator_met"] = new_numerator
        measure["measure_code"] = new_code
        measure["composite_score"] = calc.mips_composite_score(measure)
        db.bump(measure)
        return ok_object(measure, 200)


@bp.post("/rehab/mips-measures/<mid>/submit")
def submit_mips(mid: str):
    require_auth(["Therapist"])()
    measure = lookup_or_404(db.mips_measures, mid, "MIPSQualityMeasure")
    if measure["status"] != "DRAFT":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"MIPSQualityMeasure must be DRAFT to submit; current={measure['status']}",
        )
    patient = lookup_or_404(db.patients, measure["patient_id"], "Patient")
    therapist = lookup_or_404(db.therapists, measure["reporting_therapist_id"], "Therapist")
    _enforce_eligibility(patient, therapist)

    poc = lookup_or_404(db.plans_of_care, measure["plan_of_care_id"], "PlanOfCare")
    if poc["status"] not in {"ACTIVE", "RECERT_DUE", "DISCHARGED"}:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "MIPSQualityMeasure submit requires POC status in {ACTIVE, RECERT_DUE, DISCHARGED}",
        )

    with db.mutation_lock:
        measure["composite_score"] = calc.mips_composite_score(measure)
        measure["status"] = "SUBMITTED"
        db.bump(measure)
        return ok_object(measure, 200)


@bp.post("/rehab/mips-measures/<mid>/adjudicate")
def adjudicate_mips(mid: str):
    require_auth(["PlatformAdmin"])()
    measure = lookup_or_404(db.mips_measures, mid, "MIPSQualityMeasure")
    if measure["status"] != "SUBMITTED":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"MIPSQualityMeasure must be SUBMITTED to adjudicate; current={measure['status']}",
        )

    with db.mutation_lock:
        score = measure.get("composite_score")
        if score is None:
            score = 0.0
        if score >= 30.0:
            measure["status"] = "ACCEPTED"
        else:
            measure["status"] = "REJECTED"
        db.bump(measure)
        return ok_object(measure, 200)
