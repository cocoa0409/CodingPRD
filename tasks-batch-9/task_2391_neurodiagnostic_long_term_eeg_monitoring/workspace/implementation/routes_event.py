"""Seizure alerts, bedside safety interventions and event markings."""
import cascade
import clock
import config
import derive
import response
import validation
from db import base_record, db, insert
from errors import ApiError
from web import (ListResult, ObjectResult, bp, endpoint, get_alert, get_marking,
                 get_study)

ALERT_READ_ROLES = ("UnitCoordinator", "Technologist", "Nurse", "Epileptologist")
ALERT_RAISE_ROLES = ("Technologist", "Nurse", "Epileptologist")
INTERVENTION_READ_ROLES = ("UnitCoordinator", "Nurse", "Epileptologist")
MARKING_READ_ROLES = ("UnitCoordinator", "Technologist", "Nurse", "Epileptologist")
MARKING_WRITE_ROLES = ("Technologist", "Epileptologist")


def _adjudicate_marking(marking):
    marking["status"] = "ADJUDICATED"
    marking["adjudicated_at"] = clock.now()


def _retract_marking(marking, reason):
    marking["status"] = "RETRACTED"
    marking["retraction_reason"] = reason


# --- seizure alerts -------------------------------------------------------

@bp.route("/neurodiagnostics/studies/<study_id>/alerts", methods=["POST"])
@endpoint(roles=ALERT_RAISE_ROLES, mutating=True)
def create_alert(user_id, role, study_id):
    data = validation.body()
    source = validation.req_enum(data, "source", config.ALERT_SOURCES)
    study = get_study(study_id)
    detected_at = clock.now()
    alert = base_record("alert")
    alert.update({
        "study_id": study["id"],
        "source": source,
        "detected_at": detected_at,
        "triage_state": "DETECTED",
        "response_state": "AWAITING_RESPONSE",
        "response_deadline_minutes": derive.alert_response_deadline_minutes(
            study, detected_at),
        "responded_at": None,
        "latency_minutes": None,
        "adjudicated_at": None,
    })
    insert("alerts", alert)
    return ObjectResult(alert, 201)


@bp.route("/neurodiagnostics/studies/<study_id>/alerts", methods=["GET"])
@endpoint(roles=ALERT_READ_ROLES)
def list_study_alerts(user_id, role, study_id):
    from flask import request
    get_study(study_id)
    limit, offset = response.read_pagination(request.args)
    return ListResult(derive.ordered(derive.alerts_of_study(study_id)), limit, offset)


@bp.route("/neurodiagnostics/alerts/<alert_id>", methods=["GET"])
@endpoint(roles=ALERT_READ_ROLES)
def read_alert(user_id, role, alert_id):
    return ObjectResult(get_alert(alert_id))


@bp.route("/neurodiagnostics/alerts/<alert_id>/adjudicate", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def adjudicate_alert(user_id, role, alert_id):
    data = validation.body()
    classification = validation.req_enum(data, "classification", config.CLASSIFICATIONS)
    alert = get_alert(alert_id)
    # rung 6
    if alert["triage_state"] != "DETECTED":
        raise ApiError("ERR_INVALID_ALERT_STATE",
                       "Only a DETECTED alert may be adjudicated.")
    # rung 10 — a clinical finding needs a documented bedside response
    if classification == "CLINICAL" and not derive.interventions_of_alert(alert["id"]):
        raise ApiError("ERR_INTERVENTION_REQUIRED",
                       "A clinical adjudication requires a documented safety intervention.")

    alert["adjudicated_at"] = clock.now()
    if classification == "CLINICAL":
        alert["triage_state"] = "CONFIRMED_CLINICAL"
    elif classification == "SUBCLINICAL":
        alert["triage_state"] = "CONFIRMED_SUBCLINICAL"
    else:
        alert["triage_state"] = "REJECTED_ARTIFACT"

    for marking in derive.markings_of_alert(alert["id"]):
        if marking["status"] != "PROPOSED":
            continue
        if classification == "ARTIFACT":
            _retract_marking(marking, config.ARTIFACT_RETRACTION_REASON)
        else:
            _adjudicate_marking(marking)
    study = db.studies.get(alert["study_id"])
    if study is not None:
        cascade.reconcile_admission_for_study(study)
    return ObjectResult(alert)


@bp.route("/neurodiagnostics/alerts/<alert_id>/close", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def close_alert(user_id, role, alert_id):
    alert = get_alert(alert_id)
    # rung 6
    if alert["triage_state"] not in ("CONFIRMED_CLINICAL", "CONFIRMED_SUBCLINICAL",
                                     "REJECTED_ARTIFACT"):
        raise ApiError("ERR_INVALID_ALERT_STATE",
                       "Only an adjudicated alert may be closed.")
    # rung 10
    if (alert["triage_state"] == "CONFIRMED_CLINICAL"
            and alert["response_state"] == "AWAITING_RESPONSE"):
        raise ApiError("ERR_INTERVENTION_REQUIRED",
                       "A confirmed clinical event may not close with the bedside "
                       "response outstanding.")
    alert["triage_state"] = "CLOSED"
    return ObjectResult(alert)


# --- safety interventions -------------------------------------------------

@bp.route("/neurodiagnostics/alerts/<alert_id>/interventions", methods=["POST"])
@endpoint(roles=("Nurse",), mutating=True)
def create_intervention(user_id, role, alert_id):
    data = validation.body()
    kinds = validation.req_string_list(data, "interventions", config.INTERVENTION_KINDS)
    injury_observed = validation.req_bool(data, "injury_observed")
    rescue_med_given = validation.req_bool(data, "rescue_med_given")
    alert = get_alert(alert_id)
    study = db.studies.get(alert["study_id"])
    # rung 6 — the bedside response is documented only while the recording runs
    if study is None or study["acquisition_state"] not in ("ACQUIRING", "PAUSED"):
        raise ApiError("ERR_INVALID_STUDY_STATE",
                       "The study must be ACQUIRING or PAUSED to record an intervention.")

    first = len(derive.interventions_of_alert(alert["id"])) == 0
    now = clock.now()
    intervention = base_record("intervention", full_preamble=False)
    intervention.update({
        "alert_id": alert["id"],
        "nurse_user_id": user_id,
        "interventions": kinds,
        "injury_observed": injury_observed,
        "rescue_med_given": rescue_med_given,
        "recorded_at": now,
    })
    insert("interventions", intervention)

    if first and alert["response_state"] == "AWAITING_RESPONSE":
        latency = derive.floor_int(derive.minutes_between(alert["detected_at"], now))
        alert["responded_at"] = now
        alert["latency_minutes"] = latency
        if latency <= alert["response_deadline_minutes"]:
            alert["response_state"] = "RESPONDED_ON_TIME"
        else:
            alert["response_state"] = "RESPONDED_LATE"
    return ObjectResult(intervention, 201)


@bp.route("/neurodiagnostics/alerts/<alert_id>/interventions", methods=["GET"])
@endpoint(roles=INTERVENTION_READ_ROLES)
def list_alert_interventions(user_id, role, alert_id):
    from flask import request
    get_alert(alert_id)
    limit, offset = response.read_pagination(request.args)
    records = derive.ordered(derive.interventions_of_alert(alert_id))
    return ListResult(records, limit, offset)


# --- event markings -------------------------------------------------------

@bp.route("/neurodiagnostics/markings", methods=["POST"])
@endpoint(roles=MARKING_WRITE_ROLES, mutating=True)
def create_marking(user_id, role):
    data = validation.body()
    study_id = validation.req_id(data, "study_id")
    onset_at = validation.req_datetime(data, "onset_at")
    event_class = validation.req_enum(data, "event_class", config.EVENT_CLASSES)
    duration_seconds = validation.opt_int(data, "duration_seconds", default=60, minimum=1)
    alert_id = validation.opt_id(data, "alert_id")
    # rung 5 — body foreign keys in declared field order
    study = get_study(study_id)
    if alert_id is not None:
        get_alert(alert_id)
    # rung 28 — the onset must land inside a closed acquisition segment
    if not derive.onset_inside_closed_segment(study, onset_at):
        raise ApiError("ERR_MARKING_OUTSIDE_STUDY_WINDOW",
                       "onset_at does not fall inside a closed acquisition segment.")

    step = derive.taper_current_step(study["admission_id"])
    discount = (config.TAPER_PROVOKED_DISCOUNT
                if step >= config.TAPER_DISCOUNT_MIN_STEP else derive.ONE)
    weight = derive.q3(config.CLASS_WEIGHT[event_class] * discount)
    marking = base_record("marking")
    marking.update({
        "study_id": study["id"],
        "alert_id": alert_id,
        "onset_at": onset_at,
        "duration_seconds": duration_seconds,
        "event_class": event_class,
        "status": "PROPOSED",
        "taper_step_at_onset": step,
        "weight": weight,
        "adjudicated_at": None,
        "retraction_reason": None,
    })
    insert("markings", marking)
    return ObjectResult(marking, 201)


@bp.route("/neurodiagnostics/markings", methods=["GET"])
@endpoint(roles=MARKING_READ_ROLES)
def list_markings(user_id, role):
    from flask import request
    args = request.args
    limit, offset = response.read_pagination(args)
    study_id = validation.query_string(args, "study_id")
    alert_id = validation.query_string(args, "alert_id")
    status = validation.query_enum(args, "status", config.MARKING_STATUSES)
    records = []
    for marking in db.markings.values():
        if study_id and marking["study_id"] != study_id:
            continue
        if alert_id and marking.get("alert_id") != alert_id:
            continue
        if status and marking["status"] != status:
            continue
        records.append(marking)
    return ListResult(derive.ordered(records), limit, offset)


@bp.route("/neurodiagnostics/markings/<marking_id>", methods=["GET"])
@endpoint(roles=MARKING_READ_ROLES)
def read_marking(user_id, role, marking_id):
    return ObjectResult(get_marking(marking_id))


@bp.route("/neurodiagnostics/markings/<marking_id>/adjudicate", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def adjudicate_marking(user_id, role, marking_id):
    marking = get_marking(marking_id)
    # rung 6 — the marking's own dimension first, then the study's data residency
    if marking["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_MARKING_STATE",
                       "Only a PROPOSED marking may be adjudicated.")
    study = db.studies.get(marking["study_id"])
    if study is not None and study["data_state"] == "PURGED":
        raise ApiError("ERR_INVALID_DATA_STATE",
                       "The study's data has been purged.")
    _adjudicate_marking(marking)
    cascade.reconcile_admission_for_marking(marking)
    return ObjectResult(marking)


@bp.route("/neurodiagnostics/markings/<marking_id>/retract", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def retract_marking(user_id, role, marking_id):
    data = validation.body()
    retraction_reason = validation.req_string(data, "retraction_reason")
    marking = get_marking(marking_id)
    if marking["status"] not in ("PROPOSED", "ADJUDICATED"):
        raise ApiError("ERR_INVALID_MARKING_STATE",
                       "Only a PROPOSED or ADJUDICATED marking may be retracted.")
    _retract_marking(marking, retraction_reason)
    cascade.reconcile_admission_for_marking(marking)
    return ObjectResult(marking)
