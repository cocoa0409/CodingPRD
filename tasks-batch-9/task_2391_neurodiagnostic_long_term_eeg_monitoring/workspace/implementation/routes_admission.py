"""Admissions, the day ledger settlement and the medication-reduction protocol."""
from datetime import timedelta

import cascade
import clock
import config
import derive
import response
import validation
from db import base_record, db, insert
from errors import ApiError
from web import (ListResult, ObjectResult, RawResult, bp, endpoint, get_admission,
                 get_authorization, get_bed, get_patient, get_taper_plan, get_unit)

ANY_ROLE = config.ROLES
CAPTURE_ROLES = ("UnitCoordinator", "Epileptologist")
TAPER_READ_ROLES = ("UnitCoordinator", "Nurse", "Epileptologist")


@bp.route("/neurodiagnostics/admissions", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_admission(user_id, role):
    data = validation.body()
    patient_id = validation.req_id(data, "patient_id")
    authorization_id = validation.req_id(data, "authorization_id")
    unit_id = validation.req_id(data, "unit_id")
    setting = validation.req_enum(data, "setting", config.SETTINGS)
    scheduled_admit_at = validation.req_datetime(data, "scheduled_admit_at")
    target_event_count = validation.req_int(data, "target_event_count", minimum=1)
    planned_days = validation.req_int(data, "planned_days", minimum=1)
    get_patient(patient_id)
    get_authorization(authorization_id)
    get_unit(unit_id)
    admission = base_record("admission")
    admission.update({
        "patient_id": patient_id,
        "authorization_id": authorization_id,
        "unit_id": unit_id,
        "bed_id": None,
        "setting": setting,
        "scheduled_admit_at": scheduled_admit_at,
        "target_event_count": target_event_count,
        "planned_days": planned_days,
        "admitted_at": None,
        "discharged_at": None,
        "planned_discharge_at": None,
        "clinical_state": "SCHEDULED",
        "authorization_state": "AUTH_PENDING",
        "extension_count": 0,
        "last_extension_outcome": None,
        "last_extension_granted_days": 0,
        "disposition": None,
    })
    insert("admissions", admission)
    return ObjectResult(admission, 201)


@bp.route("/neurodiagnostics/admissions", methods=["GET"])
@endpoint(roles=ANY_ROLE)
def list_admissions(user_id, role):
    from flask import request
    args = request.args
    limit, offset = response.read_pagination(args)
    patient_id = validation.query_string(args, "patient_id")
    authorization_id = validation.query_string(args, "authorization_id")
    unit_id = validation.query_string(args, "unit_id")
    bed_id = validation.query_string(args, "bed_id")
    clinical_state = validation.query_enum(args, "clinical_state", config.CLINICAL_STATES)
    authorization_state = validation.query_enum(args, "authorization_state",
                                                config.AUTHORIZATION_STATES)
    records = []
    for admission in db.admissions.values():
        if patient_id and admission["patient_id"] != patient_id:
            continue
        if authorization_id and admission["authorization_id"] != authorization_id:
            continue
        if unit_id and admission["unit_id"] != unit_id:
            continue
        if bed_id and admission.get("bed_id") != bed_id:
            continue
        if clinical_state and admission["clinical_state"] != clinical_state:
            continue
        if authorization_state and admission["authorization_state"] != authorization_state:
            continue
        records.append(admission)
    return ListResult(derive.ordered(records), limit, offset)


@bp.route("/neurodiagnostics/admissions/<admission_id>", methods=["GET"])
@endpoint(roles=ANY_ROLE)
def read_admission(user_id, role, admission_id):
    return ObjectResult(get_admission(admission_id))


@bp.route("/neurodiagnostics/admissions/<admission_id>/admit", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def admit_admission(user_id, role, admission_id):
    data = validation.body()
    bed_id = validation.opt_id(data, "bed_id")
    admission = get_admission(admission_id)
    bed = get_bed(bed_id) if bed_id is not None else None

    # rung 6 — declared transition
    if admission["clinical_state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_ADMISSION_STATE",
                       "Only a SCHEDULED admission may be admitted.")
    authorization = derive.authorization_of_admission(admission)
    setting = admission["setting"]

    # rung 13 — setting agreement (silent unless the authorization is APPROVED)
    if (authorization is not None and authorization["status"] == "APPROVED"
            and setting != authorization.get("authorized_setting")):
        raise ApiError("ERR_SETTING_MISMATCH",
                       "The admission setting does not match the authorized setting.")

    # rung 14 — bed availability
    if bed is not None and setting == "INPATIENT_VEEG" and not derive.bed_is_available(bed):
        raise ApiError("ERR_BED_OCCUPANCY_CONFLICT", "The requested bed is not available.")

    # rung 15 — bed presence rules
    if setting == "INPATIENT_VEEG" and bed is None:
        raise ApiError("ERR_BED_REQUIRED_FOR_INPATIENT",
                       "An INPATIENT_VEEG admission must supply a bed_id.")
    if setting == "AMBULATORY_VEEG" and bed is not None:
        raise ApiError("ERR_BED_NOT_ALLOWED_FOR_AMBULATORY",
                       "An AMBULATORY_VEEG admission may not supply a bed_id.")

    # rung 19 — approved funding
    if authorization is None or authorization["status"] != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED",
                       "The funding authorization is not APPROVED.")

    # rung 20 — sufficient authorized days
    if authorization["days_available"] < admission["planned_days"]:
        raise ApiError("ERR_AUTHORIZATION_DAYS_EXHAUSTED",
                       "The authorization does not have enough available days.")

    # rung 21 — storage lock
    unit = derive.unit_of_admission(admission)
    if unit is not None and derive.unit_posture(unit) == "STORAGE_LOCKED":
        raise ApiError("ERR_UNIT_STORAGE_LOCKED", "The unit is storage locked.")

    now = clock.now()
    admission["admitted_at"] = now
    admission["clinical_state"] = "ADMITTED"
    admission["authorization_state"] = "AUTH_ACTIVE"
    admission["planned_discharge_at"] = now + timedelta(days=admission["planned_days"])
    if bed is not None:
        admission["bed_id"] = bed["id"]
    authorization["days_reserved"] += admission["planned_days"]
    authorization["days_available"] -= admission["planned_days"]
    return ObjectResult(admission)


@bp.route("/neurodiagnostics/admissions/<admission_id>/extension-decisions",
          methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def extension_decision(user_id, role, admission_id):
    data = validation.body()
    expected_version = validation.req_int(data, "expected_admission_version")
    admission = get_admission(admission_id)

    # rung 6
    if admission["clinical_state"] == "DISCHARGED":
        raise ApiError("ERR_INVALID_ADMISSION_STATE",
                       "A DISCHARGED admission may not be extended.")
    # rung 7
    if expected_version != admission["version"]:
        raise ApiError("ERR_STALE_ADMISSION_VERSION",
                       "expected_admission_version does not match the admission version.")
    # rung 26
    capture = derive.admission_capture(admission)
    if (capture["weighted_event_count"] == derive.ZERO
            or capture["elapsed_monitored_days"] == derive.ZERO):
        raise ApiError("ERR_NO_YIELD_BASIS",
                       "The admission has no capture yield basis for an extension.")
    # rung 27
    if admission["clinical_state"] == "CAPTURE_TARGET_MET":
        raise ApiError("ERR_TARGET_ALREADY_MET",
                       "The admission has already met its capture target.")

    result = derive.evaluate_extension(admission)
    granted = result["granted_days"]
    admission["extension_count"] += 1
    admission["last_extension_granted_days"] = granted
    admission["last_extension_outcome"] = result["outcome"]
    authorization = derive.authorization_of_admission(admission)
    if result["outcome"] == "GRANTED":
        if authorization is not None:
            authorization["days_reserved"] += granted
            authorization["days_available"] -= granted
        if admission.get("planned_discharge_at") is not None:
            admission["planned_discharge_at"] = (
                admission["planned_discharge_at"] + timedelta(days=granted))
    days_available = authorization["days_available"] if authorization else 0
    if days_available == 0 or result["outcome"] == "DENIED_AUTH_DAYS":
        if admission["authorization_state"] == "AUTH_ACTIVE":
            admission["authorization_state"] = "AUTH_EXHAUSTED"
    return ObjectResult(admission)


@bp.route("/neurodiagnostics/admissions/<admission_id>/discharge", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def discharge_admission(user_id, role, admission_id):
    data = validation.body()
    disposition = validation.req_enum(data, "disposition", config.DISPOSITIONS)
    admission = get_admission(admission_id)

    # rung 6
    if admission["clinical_state"] not in ("ADMITTED", "CAPTURE_TARGET_MET"):
        raise ApiError("ERR_INVALID_ADMISSION_STATE",
                       "Only an ADMITTED or CAPTURE_TARGET_MET admission may be discharged.")
    # rung 29
    for study in derive.studies_of_admission(admission["id"]):
        if study["acquisition_state"] in ("PREPARING", "ACQUIRING", "PAUSED"):
            raise ApiError("ERR_OPEN_STUDY_ON_DISCHARGE",
                           "A study of this admission is still running.")

    now = clock.now()
    admission["discharged_at"] = now
    admission["clinical_state"] = "DISCHARGED"
    admission["disposition"] = disposition
    elapsed = derive.admission_elapsed_days(admission)

    authorization = derive.authorization_of_admission(admission)
    if authorization is not None:
        reserved = authorization["days_reserved"]
        spent = min(reserved, derive.ceil_int(elapsed))
        authorization["days_consumed"] += spent
        authorization["days_available"] += reserved - spent
        authorization["days_reserved"] = 0
    admission["authorization_state"] = "AUTH_CLOSED"

    bed_id = admission.get("bed_id")
    if bed_id is not None:
        bed = db.beds.get(bed_id)
        if bed is not None:
            bed["released_at"] = now
            bed["turnover_clear_at"] = now + timedelta(
                minutes=config.TURNOVER_BUFFER_MINUTES)
        admission["bed_id"] = None

    for plan in derive.taper_plans_of_admission(admission["id"]):
        if plan["status"] in ("ACTIVE", "HELD"):
            plan["status"] = "ABORTED"
    return ObjectResult(admission)


@bp.route("/neurodiagnostics/admissions/<admission_id>/capture-summary", methods=["GET"])
@endpoint(roles=CAPTURE_ROLES)
def capture_summary(user_id, role, admission_id):
    admission = get_admission(admission_id)
    capture = derive.admission_capture(admission)
    return RawResult({
        "adequacy_retrospective": derive.f3(capture["capture_adequacy_index"]),
        "adequacy_prospective": derive.f3(capture["capture_adequacy_index_prospective"]),
        "weighted_event_count": derive.f3(capture["weighted_event_count"]),
        "projected_daily_yield": derive.f3(capture["projected_daily_yield"]),
        "deficit_weighted": derive.f3(capture["deficit_weighted"]),
        "elapsed_monitored_days": derive.f3(capture["elapsed_monitored_days"]),
    })


# --- taper plans ---------------------------------------------------------

@bp.route("/neurodiagnostics/taper-plans", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def create_taper_plan(user_id, role):
    data = validation.body()
    admission_id = validation.req_id(data, "admission_id")
    total_steps = validation.req_int(data, "total_steps", minimum=1)
    get_admission(admission_id)
    plan = base_record("taper_plan")
    plan.update({
        "admission_id": admission_id,
        "total_steps": total_steps,
        "current_step": 0,
        "status": "ACTIVE",
        "hold_reason": None,
    })
    insert("taper_plans", plan)
    return ObjectResult(plan, 201)


@bp.route("/neurodiagnostics/admissions/<admission_id>/taper-plans", methods=["GET"])
@endpoint(roles=TAPER_READ_ROLES)
def list_admission_taper_plans(user_id, role, admission_id):
    from flask import request
    get_admission(admission_id)
    limit, offset = response.read_pagination(request.args)
    records = derive.ordered(derive.taper_plans_of_admission(admission_id))
    return ListResult(records, limit, offset)


@bp.route("/neurodiagnostics/taper-plans/<plan_id>", methods=["GET"])
@endpoint(roles=TAPER_READ_ROLES)
def read_taper_plan(user_id, role, plan_id):
    return ObjectResult(get_taper_plan(plan_id))


@bp.route("/neurodiagnostics/taper-plans/<plan_id>/advance-step", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def advance_taper_step(user_id, role, plan_id):
    plan = get_taper_plan(plan_id)
    # rung 6
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TAPER_STATE",
                       "Only an ACTIVE taper plan may advance a step.")
    admission = db.admissions.get(plan["admission_id"])
    if admission is None or admission["clinical_state"] != "ADMITTED":
        raise ApiError("ERR_INVALID_ADMISSION_STATE",
                       "The admission must be ADMITTED to advance the taper.")
    # rung 9
    for alert in derive.alerts_of_admission(admission["id"]):
        if alert["triage_state"] == "CONFIRMED_CLINICAL":
            raise ApiError("ERR_TAPER_BLOCKED_BY_OPEN_EVENT",
                           "An unclosed confirmed clinical event blocks the taper.")
    plan["current_step"] = min(plan["current_step"] + 1, plan["total_steps"])
    if plan["current_step"] >= plan["total_steps"]:
        plan["status"] = "COMPLETED"
    return ObjectResult(plan)


@bp.route("/neurodiagnostics/taper-plans/<plan_id>/hold", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def hold_taper_plan(user_id, role, plan_id):
    data = validation.body()
    hold_reason = validation.req_string(data, "hold_reason")
    plan = get_taper_plan(plan_id)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TAPER_STATE",
                       "Only an ACTIVE taper plan may be held.")
    plan["status"] = "HELD"
    plan["hold_reason"] = hold_reason
    return ObjectResult(plan)


@bp.route("/neurodiagnostics/taper-plans/<plan_id>/resume", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def resume_taper_plan(user_id, role, plan_id):
    plan = get_taper_plan(plan_id)
    if plan["status"] != "HELD":
        raise ApiError("ERR_INVALID_TAPER_STATE",
                       "Only a HELD taper plan may be resumed.")
    admission = db.admissions.get(plan["admission_id"])
    if admission is None or admission["clinical_state"] != "ADMITTED":
        raise ApiError("ERR_INVALID_ADMISSION_STATE",
                       "The admission must be ADMITTED to resume the taper.")
    plan["status"] = "ACTIVE"
    return ObjectResult(plan)
