"""StructureSurvey and HazmatAbatement endpoints."""

from flask import Blueprint, g

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SURVEY_INCOMPLETE,
                    ERR_SOD_VIOLATION, ERR_FORBIDDEN)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_structure_survey, ser_abatement
from services import get_project, get_structure_survey, get_abatement, children
from util import req_str, req_enum, opt_str

bp = Blueprint("surveys", __name__)

SURVEY_TYPES = ("INITIAL", "ADDENDUM")
MATERIAL_TYPES = ("ASBESTOS", "LEAD_PAINT", "PCB", "MERCURY", "OTHER")
SURVEY_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "Surveyor",
                     "AbatementSupervisor", "ClearanceOfficer")
SURVEY_CREATABLE_PHASES = ("DRAFT", "SURVEY_PHASE", "PRECONDITIONS_PENDING")

ABATEMENT_ACTIONS = ("START", "REQUEST_CLEARANCE", "CERTIFY_CLEARANCE", "FAIL_CLEARANCE")
ABATEMENT_ACTION_ROLES = {
    "START": ("AbatementSupervisor",),
    "REQUEST_CLEARANCE": ("AbatementSupervisor",),
    "CERTIFY_CLEARANCE": ("ClearanceOfficer",),
    "FAIL_CLEARANCE": ("ClearanceOfficer",),
}


@bp.post("/demolition/projects/<pid>/structure-surveys")
@require_roles("Surveyor")
def create_structure_survey(pid):
    b = body()
    label = req_str(b, "structure_label")
    survey_type = "INITIAL"
    if "survey_type" in b and b["survey_type"] is not None:
        survey_type = req_enum(b, "survey_type", SURVEY_TYPES)
    project = get_project(pid)
    if project["status"] not in SURVEY_CREATABLE_PHASES:
        raise err(ERR_INVALID_STATE, "structure surveys cannot be created in this project phase")

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "structure_label": label,
        "survey_type": survey_type,
        "status": "IN_PROGRESS",
        "hazmat_found": False,
        "findings_summary": "",
        "completed_at": None,
    })
    store.structure_surveys[rec["id"]] = rec

    # Project machine: first survey under DRAFT advances to SURVEY_PHASE;
    # creation under PRECONDITIONS_PENDING regresses to SURVEY_PHASE.
    if project["status"] in ("DRAFT", "PRECONDITIONS_PENDING"):
        project["status"] = "SURVEY_PHASE"
        touch(project)
    return success(ser_structure_survey(rec), status=201)


@bp.get("/demolition/projects/<pid>/structure-surveys")
@require_roles(*SURVEY_READ_ROLES)
def list_structure_surveys(pid):
    project = get_project(pid)
    return list_response(children(store.structure_surveys, "project_id", project["id"]),
                         ser_structure_survey)


@bp.get("/demolition/structure-surveys/<sid>")
@require_roles(*SURVEY_READ_ROLES)
def get_one_structure_survey(sid):
    return success(ser_structure_survey(get_structure_survey(sid)))


@bp.post("/demolition/structure-surveys/<sid>/transition")
@require_roles("Surveyor")
def structure_survey_transition(sid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in ("COMPLETE", "REOPEN"):
        raise err(ERR_VALIDATION, "invalid action")
    hazmat_found = None
    if "hazmat_found" in b and b["hazmat_found"] is not None:
        if not isinstance(b["hazmat_found"], bool):
            raise err(ERR_VALIDATION, "hazmat_found must be a boolean")
        hazmat_found = b["hazmat_found"]
    findings = opt_str(b, "findings_summary")

    survey = get_structure_survey(sid)
    project = store.projects[survey["project_id"]]

    if action == "COMPLETE":
        if survey["status"] != "IN_PROGRESS":
            raise err(ERR_INVALID_STATE, "COMPLETE requires IN_PROGRESS")
        if hazmat_found is not None:
            survey["hazmat_found"] = hazmat_found
        if findings is not None:
            survey["findings_summary"] = findings
        survey["completed_at"] = now()
        survey["status"] = "COMPLETE"
        touch(survey)
        # Bubble-up: all surveys COMPLETE while SURVEY_PHASE -> PRECONDITIONS_PENDING.
        siblings = children(store.structure_surveys, "project_id", project["id"])
        if project["status"] == "SURVEY_PHASE" and siblings and all(
                s["status"] == "COMPLETE" for s in siblings):
            project["status"] = "PRECONDITIONS_PENDING"
            touch(project)
    else:  # REOPEN
        if survey["status"] != "COMPLETE":
            raise err(ERR_INVALID_STATE, "REOPEN requires COMPLETE")
        if project["status"] not in ("SURVEY_PHASE", "PRECONDITIONS_PENDING"):
            raise err(ERR_INVALID_STATE, "survey is locked at this project phase")
        survey["status"] = "IN_PROGRESS"
        survey["completed_at"] = None
        touch(survey)
        if project["status"] == "PRECONDITIONS_PENDING":
            project["status"] = "SURVEY_PHASE"
            touch(project)

    return success(ser_structure_survey(survey))


@bp.post("/demolition/structure-surveys/<sid>/abatements")
@require_roles("Surveyor", "AbatementSupervisor")
def create_abatement(sid):
    b = body()
    material_type = req_enum(b, "material_type", MATERIAL_TYPES)
    description = req_str(b, "description")
    containment_method = req_str(b, "containment_method")
    survey = get_structure_survey(sid)

    rec = new_record()
    rec.update({
        "structure_survey_id": survey["id"],
        "material_type": material_type,
        "description": description,
        "containment_method": containment_method,
        "status": "IDENTIFIED",
        "started_by_user_id": None,
        "certified_by_user_id": None,
        "certified_at": None,
    })
    store.abatements[rec["id"]] = rec
    return success(ser_abatement(rec), status=201)


@bp.get("/demolition/structure-surveys/<sid>/abatements")
@require_roles(*SURVEY_READ_ROLES)
def list_abatements(sid):
    survey = get_structure_survey(sid)
    return list_response(children(store.abatements, "structure_survey_id", survey["id"]),
                         ser_abatement)


@bp.post("/demolition/abatements/<aid>/transition")
@require_roles("AbatementSupervisor", "ClearanceOfficer")
def abatement_transition(aid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in ABATEMENT_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    abatement = get_abatement(aid)
    if g.role not in ABATEMENT_ACTION_ROLES[action]:
        raise err(ERR_FORBIDDEN, "role not permitted for this action")
    status = abatement["status"]

    if action == "START":
        if status not in ("IDENTIFIED", "CLEARANCE_FAILED"):
            raise err(ERR_INVALID_STATE, "START requires IDENTIFIED or CLEARANCE_FAILED")
        abatement["started_by_user_id"] = g.user_id
        abatement["status"] = "ABATEMENT_ACTIVE"
    elif action == "REQUEST_CLEARANCE":
        if status != "ABATEMENT_ACTIVE":
            raise err(ERR_INVALID_STATE, "REQUEST_CLEARANCE requires ABATEMENT_ACTIVE")
        parent = store.structure_surveys[abatement["structure_survey_id"]]
        if parent["status"] != "COMPLETE":
            raise err(ERR_SURVEY_INCOMPLETE, "parent structure survey is not COMPLETE")
        abatement["status"] = "CLEARANCE_PENDING"
    elif action == "CERTIFY_CLEARANCE":
        if status != "CLEARANCE_PENDING":
            raise err(ERR_INVALID_STATE, "CERTIFY_CLEARANCE requires CLEARANCE_PENDING")
        if g.user_id == abatement["started_by_user_id"]:
            raise err(ERR_SOD_VIOLATION, "certifier must differ from the abatement starter")
        abatement["certified_by_user_id"] = g.user_id
        abatement["certified_at"] = now()
        abatement["status"] = "CLEARANCE_CERTIFIED"
    else:  # FAIL_CLEARANCE
        if status != "CLEARANCE_PENDING":
            raise err(ERR_INVALID_STATE, "FAIL_CLEARANCE requires CLEARANCE_PENDING")
        abatement["status"] = "CLEARANCE_FAILED"

    touch(abatement)
    return success(ser_abatement(abatement))
