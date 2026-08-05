"""Occlusion (patching) prescriptions for amblyopia."""

from flask import Blueprint, request

import calc
import config
import lookup
import serialize
from auth import authenticate, require_owner
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, ordered, touch
from validate import filter_enum, json_body

bp = Blueprint("occlusion", __name__)
P = config.API_PREFIX


@bp.post(P + "/occlusion-prescriptions")
def create_prescription():
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    patient_id = b.str_req("patient_id")
    source_assessment_id = b.str_req("source_assessment_id")
    b.enum_shape_req("severity")
    baseline_acuity = b.num_req("baseline_acuity_logmar")
    severity = b.enum_req("severity", config.SEVERITIES)

    lookup.patient_or_404(patient_id)                                      # rung 5
    source = lookup.assessment_or_404(source_assessment_id)                # rung 7
    lookup.gate_for_patient_id(patient_id)                                 # rung 12

    # The age band reads the SOURCE ASSESSMENT's stored patient_age_years;
    # OcclusionPrescription itself carries no patient_age_years field.
    band, hours = calc.occlusion_daily_dose(source["patient_age_years"], severity)

    row = base_row()
    row.update({
        "patient_id": patient_id,
        "source_assessment_id": source_assessment_id,
        "severity": severity,
        "age_band": band,
        "prescribed_daily_hours": hours,
        "current_daily_hours": hours,
        "taper_step_count": 0,
        "logged_days": 0,
        "adherent_days": 0,
        "adherence_pct": 0.0,
        "baseline_acuity_logmar": baseline_acuity,
        "status": "ACTIVE",
    })
    db.occlusions[row["id"]] = row
    return created(serialize.occlusion(row))


@bp.get(P + "/occlusion-prescriptions/<id>")
def get_prescription(id):
    caller = authenticate(config.READ_ROLES_WITH_PATIENT)
    row = db.occlusions.get(id)
    if row is not None:
        require_owner(caller, row["patient_id"])
    return ok(serialize.occlusion(lookup.occlusion_or_404(id)))


@bp.get(P + "/occlusion-prescriptions")
def list_prescriptions():
    caller = authenticate(config.READ_ROLES_WITH_PATIENT)
    limit, offset = pagination(request.args)
    severity = filter_enum(request.args, "severity", config.SEVERITIES)
    status = filter_enum(request.args, "status", config.OCCLUSION_STATUSES)
    patient_id = request.args.get("patient_id")
    source_assessment_id = request.args.get("source_assessment_id")
    if caller.is_patient:
        patient_id = caller.user_id

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if source_assessment_id and row["source_assessment_id"] != source_assessment_id:
            return False
        if severity and row["severity"] != severity:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.occlusions, match), limit, offset, serialize.occlusion)


@bp.post(P + "/occlusion-prescriptions/<id>/adherence")
def log_adherence(id):
    caller = authenticate([config.ROLE_PATIENT])
    peek = db.occlusions.get(id)
    if peek is not None:                                                   # rung 2 ownership
        require_owner(caller, peek["patient_id"])
    b = json_body()
    logged_delta = b.int_req("logged_days_delta", non_negative=True)
    adherent_delta = b.int_req("adherent_days_delta", non_negative=True)
    presc = lookup.occlusion_or_404(id)                                    # rung 11
    lookup.gate_for_patient_id(presc["patient_id"])                        # rung 12

    presc["logged_days"] += logged_delta
    presc["adherent_days"] += adherent_delta
    presc["adherence_pct"] = calc.adherence_pct(presc["logged_days"], presc["adherent_days"])
    touch(presc)
    return ok(serialize.occlusion(presc))


@bp.post(P + "/occlusion-prescriptions/<id>/taper")
def taper(id):
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    current_acuity = b.num_req("current_acuity_logmar")
    presc = lookup.occlusion_or_404(id)                                    # rung 11
    lookup.gate_for_patient_id(presc["patient_id"])                        # rung 12
    if presc["status"] not in ("ACTIVE", "TAPERED"):                       # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE or TAPERED prescription may be tapered.")

    gain = calc.r2(calc.D(presc["baseline_acuity_logmar"]) - calc.D(current_acuity))
    if (calc.D(presc["adherence_pct"]) < calc.D(config.ADHERENCE_MIN_PCT_FOR_TAPER)
            or gain < calc.D(config.TAPER_ACUITY_GATE_LOGMAR)):            # rung 34
        raise ApiError("ERR_TAPER_GATE_NOT_MET")

    new_hours = presc["current_daily_hours"] - config.TAPER_STEP_HOURS
    if new_hours <= 0:
        presc["current_daily_hours"] = 0
        presc["status"] = "COMPLETED"
    else:
        presc["current_daily_hours"] = new_hours
        presc["status"] = "TAPERED"
    presc["taper_step_count"] += 1
    touch(presc)
    return ok(serialize.occlusion(presc))
