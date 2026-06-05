"""HEDIS measure endpoints and compliance-rate read (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from db import stamp_create, touch
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import require
from response import ok_object
from routes.common import lookup_or_404
from services import calc, derive
from validation import (
    get_body,
    optional_bool,
    optional_enum,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("hedis", __name__)

MEASURE_TYPES = {"CIS_FLU", "BCS_MAMMOGRAM", "CBP_BP_CONTROL", "MED_ADHERENCE"}
METHODS = {"ADMINISTRATIVE", "HYBRID"}


@bp.route("/hedis-measures", methods=["POST"])
def create_hedis_measure():
    require(["QualityAnalyst"])
    body = get_body()

    # Priority 4: patient_id FK existence.
    pid_raw = body.get("patient_id")
    if isinstance(pid_raw, str) and pid_raw not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")

    patient_id = require_str(body, "patient_id")
    measure_type = require_enum(body, "measure_type", MEASURE_TYPES)
    measurement_year = require_int(body, "measurement_year", minimum=2000)
    method = optional_enum(body, "method", METHODS, default="ADMINISTRATIVE")
    chart_confirmed = optional_bool(body, "chart_confirmed", default=False)

    if patient_id not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")
    patient = db.patients[patient_id]

    eligible = calc.hedis_eligibility(
        patient["date_of_birth"], patient["sex"], measure_type, measurement_year
    )
    rec = stamp_create({
        "patient_id": patient_id,
        "measure_type": measure_type,
        "measurement_year": measurement_year,
        "method": method,
        "eligible": eligible,
        "status": "GAP",
        "chart_confirmed": chart_confirmed,
    })
    db.hedis_measures[rec["id"]] = rec
    # New GAP measure may add to the patient's open-care-gap count.
    derive.recompute_patient_open_care_gaps(patient)
    return ok_object(derive.serialize_hedis_measure(rec), 201)


@bp.route("/hedis-measures/<mid>", methods=["GET"])
def get_hedis_measure(mid):
    require(["QualityAnalyst", "Provider", "FrontDesk"])
    rec = lookup_or_404(db.hedis_measures, mid, "HedisMeasure")
    return ok_object(derive.serialize_hedis_measure(rec), 200)


@bp.route("/hedis-measures/<mid>/exclude", methods=["POST"])
def exclude_hedis_measure(mid):
    require(["QualityAnalyst"])
    rec = lookup_or_404(db.hedis_measures, mid, "HedisMeasure")
    # EXCLUDED is reachable from any non-excluded status (PRD §3.10 narrative
    # places no state precondition beyond not-already-excluded).
    if rec["status"] == "EXCLUDED":
        raise APIError(ERR_INVALID_STATE, 409, "Measure is already EXCLUDED")
    rec["status"] = "EXCLUDED"
    touch(rec)
    patient = db.patients.get(rec["patient_id"])
    if patient is not None:
        derive.recompute_patient_open_care_gaps(patient)
    return ok_object(derive.serialize_hedis_measure(rec), 200)


@bp.route("/hedis/rate", methods=["GET"])
def hedis_rate():
    require(["QualityAnalyst"])
    measure_type = request.args.get("measure_type")
    measurement_year = request.args.get("measurement_year")
    method = request.args.get("method")

    if measure_type is None or measure_type not in MEASURE_TYPES:
        raise APIError(ERR_INVALID_REQUEST, 422, "measure_type required and must be valid")
    if method is None or method not in METHODS:
        raise APIError(ERR_INVALID_REQUEST, 422, "method required and must be valid")
    if measurement_year is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "measurement_year required")
    try:
        year = int(measurement_year)
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 422, "measurement_year must be an integer")

    population = [
        m for m in db.hedis_measures.values()
        if m["measure_type"] == measure_type
        and m["measurement_year"] == year
        and m["eligible"] is True
        and m["status"] != "EXCLUDED"
    ]
    denominator = len(population)
    if method == "ADMINISTRATIVE":
        numerator = sum(1 for m in population if m["status"] == "NUMERATOR_COMPLIANT")
    else:  # HYBRID
        numerator = sum(
            1 for m in population
            if m["status"] == "NUMERATOR_COMPLIANT"
            or (m["status"] == "GAP" and m["chart_confirmed"] is True)
        )
    rate_pct = calc.hedis_rate_pct(numerator, denominator)

    return ok_object({
        "measure_type": measure_type,
        "measurement_year": year,
        "method": method,
        "numerator": numerator,
        "denominator": denominator,
        "rate_pct": rate_pct,
    }, 200)
