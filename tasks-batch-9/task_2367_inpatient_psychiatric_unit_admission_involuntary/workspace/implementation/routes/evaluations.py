"""Emergency psychiatric evaluations (PRD §3.2)."""

from flask import Blueprint

import calc
import serializers
from auth import ANY_ROLE, ATTENDING_PSYCHIATRIST, INTAKE_CLINICIAN, context
from envelope import list_response, object_response
from errors import fail
from store import base_row, db, ordered, touch
from validation import apply_filters, body, filters, pagination, vbool, vstr

bp = Blueprint("evaluations", __name__)

CLINICAL_ROLES = (INTAKE_CLINICIAN, ATTENDING_PSYCHIATRIST)


@bp.post("/behavioral-health/evaluations")
def create_evaluation():
    user_id, _role = context(CLINICAL_ROLES)
    data = body()
    patient_id = vstr(data, "patient_id")
    danger_to_self = vbool(data, "danger_to_self")
    danger_to_others = vbool(data, "danger_to_others")
    grave_disability = vbool(data, "grave_disability")
    capacity_present = vbool(data, "capacity_present")
    clinical_summary = vstr(data, "clinical_summary")

    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_PATIENT_NOT_FOUND", "patient not found")

    row = base_row()
    started_at = db.now()
    prior = calc.prior_admission_count_30d(patient_id, started_at)
    score, tier, recommended = calc.acuity_score_and_tier(
        danger_to_self, danger_to_others, grave_disability, capacity_present, prior
    )
    row.update(
        {
            "patient_id": patient_id,
            "evaluating_clinician_id": user_id,
            "evaluation_started_at": started_at,
            "danger_to_self": danger_to_self,
            "danger_to_others": danger_to_others,
            "grave_disability": grave_disability,
            "capacity_present": capacity_present,
            "clinical_summary": clinical_summary,
            "prior_admission_count_30d": prior,
            "acuity_score": score,
            "acuity_tier": tier,
            "recommended_status": recommended,
            "status": "DRAFT",
            "signed_at": None,
        }
    )
    db.evaluations[row["id"]] = row
    return object_response(serializers.evaluation(row), 201)


@bp.post("/behavioral-health/evaluations/<evaluation_id>/sign")
def sign_evaluation(evaluation_id):
    context(CLINICAL_ROLES)
    body()
    row = db.evaluations.get(evaluation_id)
    if row is None:
        fail("ERR_EVALUATION_NOT_FOUND", "evaluation not found")
    if row["status"] != "DRAFT":
        fail("ERR_EVALUATION_ALREADY_SIGNED", "evaluation is already signed")

    # Signature freezes the record: nothing derived is recomputed here.
    row["status"] = "SIGNED"
    row["signed_at"] = db.now()
    touch(row)
    return object_response(serializers.evaluation(row))


@bp.get("/behavioral-health/evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    context(ANY_ROLE)
    row = db.evaluations.get(evaluation_id)
    if row is None:
        fail("ERR_EVALUATION_NOT_FOUND", "evaluation not found")
    return object_response(serializers.evaluation(row))


@bp.get("/behavioral-health/evaluations")
def list_evaluations():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.evaluations.values()),
        filters("patient_id", "evaluating_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.evaluation(r) for r in page], limit, offset, total)
