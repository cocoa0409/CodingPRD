from flask import Blueprint, request

from db import store
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_id,
    f_bool,
    f_int,
    f_enum,
    f_dt,
    ok,
    paginate,
)
from errors import ApiError
from services import (
    get_project,
    get_worker,
    get_incident,
    new_entity,
    ser_incident,
    bump,
    recompute_posture,
)

bp = Blueprint("incidents", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)

INCIDENT_TYPES = {"INJURY", "ILLNESS", "NEAR_MISS", "PROPERTY_DAMAGE"}
INCIDENT_SEVERITIES = {"MINOR", "SERIOUS", "CRITICAL", "FATALITY"}


@bp.route("/safety/incidents", methods=["POST"])
def create_incident():
    require_roles("SiteSuperintendent")
    b = body()
    # priority 3: FK existence + same-project rule
    raw_pid = b.get("project_id")
    project = get_project(raw_pid) if isinstance(raw_pid, str) else None
    raw_wid = b.get("worker_id")
    if isinstance(raw_wid, str) and project is not None:
        w = store.workers.get(raw_wid)
        if w is None or w["project_id"] != project["id"]:
            raise ApiError("ERR_WORKER_NOT_FOUND", 404, "No Worker with the given id")
    # priority 4: shape
    reject_unknown(
        b,
        {
            "project_id",
            "worker_id",
            "incident_type",
            "severity",
            "occurred_at",
            "work_related",
            "description",
        },
    )
    project_id = f_str(b, "project_id")
    if project is None:
        project = get_project(project_id)
    worker_id = f_id(b, "worker_id")
    if worker_id is not None:
        w = store.workers.get(worker_id)
        if w is None or w["project_id"] != project_id:
            raise ApiError("ERR_WORKER_NOT_FOUND", 404, "No Worker with the given id")
    incident_type = f_enum(b, "incident_type", INCIDENT_TYPES)
    severity = f_enum(b, "severity", INCIDENT_SEVERITIES)
    occurred_at = f_dt(b, "occurred_at")
    work_related = f_bool(b, "work_related")
    description = f_str(b, "description")
    i = new_entity()
    i.update(
        {
            "project_id": project_id,
            "worker_id": worker_id,
            "incident_type": incident_type,
            "severity": severity,
            "occurred_at": occurred_at,
            "work_related": work_related,
            "description": description,
            "status": "REPORTED",
            "investigator_user_id": None,
            "investigation_notes": "",
            "medical_treatment_beyond_first_aid": False,
            "days_away_from_work": 0,
            "restricted_duty": False,
            "loss_of_consciousness": False,
            "significant_diagnosis": False,
            "is_osha_recordable": None,
        }
    )
    store.incidents[i["id"]] = i
    # CRITICAL/FATALITY creation freezes posture (with permit cascade)
    recompute_posture(project)
    return ok(ser_incident(i), 201)


@bp.route("/safety/incidents", methods=["GET"])
def list_incidents():
    require_roles(*ALL_ROLES)
    records = list(store.incidents.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [i for i in records if i["project_id"] == pid]
    wid = request.args.get("worker_id")
    if wid is not None:
        records = [i for i in records if i["worker_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    return paginate(records, ser_incident)


@bp.route("/safety/incidents/<incidentId>", methods=["GET"])
def get_one_incident(incidentId):
    require_roles(*ALL_ROLES)
    return ok(ser_incident(get_incident(incidentId)))


@bp.route("/safety/incidents/<incidentId>/investigate", methods=["POST"])
def investigate_incident(incidentId):
    uid, _ = require_roles("SafetyInspector")
    incident = get_incident(incidentId)
    b = body()
    reject_unknown(b, {"investigation_notes"})
    notes = f_str(b, "investigation_notes")
    if incident["status"] != "REPORTED":
        raise ApiError(
            "ERR_INCIDENT_INVALID_STATE", 409, "investigate requires status REPORTED"
        )
    incident["status"] = "UNDER_INVESTIGATION"
    incident["investigator_user_id"] = uid
    incident["investigation_notes"] = notes
    bump(incident)
    return ok(ser_incident(incident))


@bp.route("/safety/incidents/<incidentId>/determination", methods=["POST"])
def determination_incident(incidentId):
    uid, _ = require_roles("SafetyManager")
    incident = get_incident(incidentId)
    b = body()
    reject_unknown(
        b,
        {
            "medical_treatment_beyond_first_aid",
            "days_away_from_work",
            "restricted_duty",
            "loss_of_consciousness",
            "significant_diagnosis",
        },
    )
    mtbfa = f_bool(b, "medical_treatment_beyond_first_aid", required=False, default=False)
    days_away = f_int(b, "days_away_from_work", required=False, default=0, min_v=0)
    restricted_duty = f_bool(b, "restricted_duty", required=False, default=False)
    loc = f_bool(b, "loss_of_consciousness", required=False, default=False)
    sig_diag = f_bool(b, "significant_diagnosis", required=False, default=False)
    if incident["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_INCIDENT_INVALID_STATE",
            409,
            "determination requires status UNDER_INVESTIGATION",
        )
    if uid == incident["investigator_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Determination user must differ from the investigator",
        )
    incident["medical_treatment_beyond_first_aid"] = mtbfa
    incident["days_away_from_work"] = days_away
    incident["restricted_duty"] = restricted_duty
    incident["loss_of_consciousness"] = loc
    incident["significant_diagnosis"] = sig_diag
    incident["is_osha_recordable"] = bool(
        incident["work_related"]
        and (mtbfa or days_away > 0 or restricted_duty or loc or sig_diag)
    )
    incident["status"] = "DETERMINATION_MADE"
    bump(incident)
    return ok(ser_incident(incident))


@bp.route("/safety/incidents/<incidentId>/close", methods=["POST"])
def close_incident(incidentId):
    require_roles("SafetyManager")
    incident = get_incident(incidentId)
    b = body()
    reject_unknown(b, set())
    if incident["status"] != "DETERMINATION_MADE":
        raise ApiError(
            "ERR_INCIDENT_INVALID_STATE",
            409,
            "close requires status DETERMINATION_MADE",
        )
    if incident["is_osha_recordable"] is True and incident["worker_id"] is not None:
        resulted = any(
            d["incident_id"] == incident["id"]
            and d["test_type"] == "POST_INCIDENT"
            and d["status"] in ("NEGATIVE", "POSITIVE")
            for d in store.drugtests.values()
        )
        if not resulted:
            raise ApiError(
                "ERR_DRUG_TEST_REQUIRED",
                409,
                "Closing a recordable incident with an involved worker requires a "
                "resulted POST_INCIDENT drug test",
            )
    incident["status"] = "CLOSED"
    bump(incident)
    # posture recompute (may lift FROZEN); suspended permits stay suspended
    recompute_posture(get_project(incident["project_id"]))
    return ok(ser_incident(incident))
