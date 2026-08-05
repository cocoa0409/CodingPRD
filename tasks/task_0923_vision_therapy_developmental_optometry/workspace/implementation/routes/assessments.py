"""The binocular battery: creation, instrument rows, finalize, sign, amend."""

from flask import Blueprint, request

import calc
import cascades
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, now_iso, ordered, touch
from validate import filter_enum, json_body

bp = Blueprint("assessments", __name__)
P = config.API_PREFIX

_METRIC_VALUE_FIELDS = {
    "NPC": ("npc_break_cm", "npc_recovery_cm"),
    "ACCOMMODATIVE_AMPLITUDE": ("amplitude_d",),
    "VERGENCE_BASE_OUT": ("vergence_bo_break_pd",),
    "VISUAL_ACUITY": ("acuity_logmar",),
    "SYMPTOM_SURVEY": ("ciss_score",),
}


@bp.post(P + "/assessments")
def create_assessment():
    authenticate([config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST])
    b = json_body()
    patient_id = b.str_req("patient_id")
    b.enum_shape_req("assessment_type")
    b.enum_shape_req("purpose")
    encounter_date = b.date_req("encounter_date")
    performed_by = b.str_req("performed_by_therapist_id")
    plan_id = b.str_opt("plan_id")
    assessment_type = b.enum_req("assessment_type", config.ASSESSMENT_TYPES)
    purpose = b.enum_req("purpose", config.ASSESSMENT_PURPOSES)
    # "a REASSESSMENT requires a plan_id naming that plan, while the initial
    #  EVALUATION leaves plan_id null" (PRD §3.1) -- a rung-3 required field.
    if assessment_type == "REASSESSMENT" and not plan_id:
        raise ApiError("ERR_VALIDATION", "A REASSESSMENT requires plan_id.")
    if assessment_type == "EVALUATION":
        plan_id = None

    patient = lookup.patient_or_404(patient_id)                            # rung 5
    if plan_id:
        lookup.plan_or_404(plan_id)                                        # rung 8
    lookup.therapist_or_404(performed_by)                                  # rung 11
    lookup.discharge_gate(patient)                                         # rung 12

    row = base_row()
    row.update({
        "patient_id": patient_id,
        "plan_id": plan_id,
        "performed_by_therapist_id": performed_by,
        "signed_by_therapist_id": None,
        "assessment_type": assessment_type,
        "purpose": purpose,
        "encounter_date": encounter_date,
        "patient_age_years": calc.patient_age_years(patient["date_of_birth"], encounter_date),
        "status": "DRAFT",
        "amendment_count": 0,
        "signed_at": None,
        "therapy_indicated": False,
        "discharge_metric_met": False,
        "composite_progress_score": None,
        "symptom_improvement_pct": None,
        "improvement_delta_points": None,
        "plateau_flag": False,
        "red_flag_present": False,
    })
    db.assessments[row["id"]] = row
    return created(serialize.assessment(row))


@bp.get(P + "/assessments/<id>")
def get_assessment(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.assessment(lookup.assessment_or_404(id)))


@bp.get(P + "/assessments")
def list_assessments():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    assessment_type = filter_enum(request.args, "assessment_type", config.ASSESSMENT_TYPES)
    purpose = filter_enum(request.args, "purpose", config.ASSESSMENT_PURPOSES)
    status = filter_enum(request.args, "status", config.ASSESSMENT_STATUSES)
    patient_id = request.args.get("patient_id")
    plan_id = request.args.get("plan_id")
    performed_by = request.args.get("performed_by_therapist_id")
    signed_by = request.args.get("signed_by_therapist_id")

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if plan_id and row["plan_id"] != plan_id:
            return False
        if performed_by and row["performed_by_therapist_id"] != performed_by:
            return False
        if signed_by and row["signed_by_therapist_id"] != signed_by:
            return False
        if assessment_type and row["assessment_type"] != assessment_type:
            return False
        if purpose and row["purpose"] != purpose:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.assessments, match), limit, offset, serialize.assessment)


@bp.post(P + "/assessments/<id>/measurements")
def create_measurement(id):
    authenticate([config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST,
                  config.ROLE_THERAPY_ASSISTANT])
    b = json_body()
    b.enum_shape_req("metric_code")                                        # rung 3
    b.enum_shape_req("eye")
    red_flag = b.bool_opt("red_flag", False)
    metric_code = b.enum_req("metric_code", config.METRIC_CODES)           # rung 4
    eye = b.enum_req("eye", config.EYES)

    values = {}
    for field in _METRIC_VALUE_FIELDS[metric_code]:                        # rung 3 (metric shape)
        if field == "ciss_score":
            values[field] = b.int_req(field, minimum=0, maximum=config.CISS_MAX_SCORE)
        else:
            values[field] = b.num_req(field)

    assessment = lookup.assessment_or_404(id)                              # rung 7
    lookup.gate_for_patient_id(assessment["patient_id"])                   # rung 12

    row = base_row(with_version=False)
    row.update({
        "assessment_id": assessment["id"],
        "metric_code": metric_code,
        "eye": eye,
        "npc_break_cm": values.get("npc_break_cm"),
        "npc_recovery_cm": values.get("npc_recovery_cm"),
        "amplitude_d": values.get("amplitude_d"),
        "vergence_bo_break_pd": values.get("vergence_bo_break_pd"),
        "acuity_logmar": values.get("acuity_logmar"),
        "ciss_score": values.get("ciss_score"),
        "red_flag": red_flag,
        "reference_variant": None,
        "expected_min_value": None,
        "expected_band_high": None,
        "within_reference_band": False,
        "diagnostic_flag": False,
    })
    calc.apply_measurement_band(row, assessment)
    db.measurements[row["id"]] = row
    return created(serialize.measurement(row))


@bp.get(P + "/assessments/<id>/measurements")
def list_measurements(id):
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    metric_code = filter_enum(request.args, "metric_code", config.METRIC_CODES)
    lookup.assessment_or_404(id)

    def match(row):
        if row["assessment_id"] != id:
            return False
        if metric_code and row["metric_code"] != metric_code:
            return False
        return True

    return paginate(ordered(db.measurements, match), limit, offset, serialize.measurement)


@bp.post(P + "/assessments/<id>/finalize")
def finalize_assessment(id):
    authenticate([config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST])
    json_body()
    assessment = lookup.assessment_or_404(id)                              # rung 7
    # rung 3: "Finalizing an assessment requires at least one child measurement
    # whose metric_code is NPC."  It can only be evaluated once the parent row
    # is resolved, but it still pre-empts rungs 12 and 14.
    if calc.latest_metric(assessment["id"], "NPC") is None:
        raise ApiError("ERR_VALIDATION", "Finalize requires at least one NPC measurement.")
    lookup.gate_for_patient_id(assessment["patient_id"])                   # rung 12
    if assessment["status"] != "DRAFT":                                    # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT battery may be finalized.")

    cascades.finalize_assessment(assessment)
    return ok(serialize.assessment(assessment))


@bp.post(P + "/assessments/<id>/sign")
def sign_assessment(id):
    caller = authenticate([config.ROLE_OPTOMETRIST])
    json_body()
    assessment = lookup.assessment_or_404(id)                              # rung 7
    lookup.gate_for_patient_id(assessment["patient_id"])                   # rung 12
    if assessment["status"] != "FINALIZED":                                # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a FINALIZED battery may be signed.")
    if (assessment["assessment_type"] == "REASSESSMENT"                    # rung 17
            and caller.user_id == assessment["performed_by_therapist_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    assessment["status"] = "SIGNED"
    assessment["signed_by_therapist_id"] = caller.user_id
    assessment["signed_at"] = now_iso()
    touch(assessment)

    patient = db.patients.get(assessment["patient_id"])
    if (assessment["assessment_type"] == "EVALUATION" and patient is not None
            and patient["clinical_status"] == "INTAKE"):
        patient["clinical_status"] = "ACTIVE"
        touch(patient)
    return ok(serialize.assessment(assessment))


@bp.post(P + "/assessments/<id>/amend")
def amend_assessment(id):
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    b.str_opt("amendment_reason")
    assessment = lookup.assessment_or_404(id)                              # rung 7
    lookup.gate_for_patient_id(assessment["patient_id"])                   # rung 12
    if assessment["status"] != "SIGNED":                                   # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a SIGNED battery may be amended.")
    if assessment["amendment_count"] >= config.MAX_ASSESSMENT_AMENDMENTS:
        raise ApiError("ERR_INVALID_STATE", "This battery has reached its amendment cap.")

    assessment["status"] = "DRAFT"
    assessment["amendment_count"] += 1
    assessment["signed_by_therapist_id"] = None
    assessment["signed_at"] = None
    touch(assessment)
    return ok(serialize.assessment(assessment))
