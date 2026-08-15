"""Project endpoints: create/list/get, phase transitions, release gate,
resume, and the OCC-guarded engineering pin."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_PROJECT_STOPPED,
                    ERR_STALE_VERSION, ERR_SURVEY_INCOMPLETE, ERR_HAZMAT_UNRESOLVED,
                    ERR_UTILITY_UNVERIFIED, ERR_PERMIT_NOT_ACTIVE,
                    ERR_ENGINEERING_NOT_CERTIFIED, ERR_ENGINEERING_PIN_STALE,
                    ERR_NOTIFICATIONS_INCOMPLETE, ERR_NOTIFICATION_WINDOW_OPEN,
                    ERR_BACKFILL_NOT_APPROVED, ERR_NOT_FOUND)
from middleware import require_roles, body, ALL_ROLES
from response import success, list_response
from serializers import ser_project
from services import (get_project, get_engineering_survey, project_surveys,
                      project_abatements, project_disconnects, project_permits,
                      project_notifications, project_backfill_plans,
                      notification_wait_window_open, BACKFILL_APPROVED_OR_LATER)
from util import req_str, req_int, opt_number, is_date_str

bp = Blueprint("projects", __name__)

PHASE_ACTIONS = ("START_DEMOLITION", "COMPLETE_STRUCTURE_REMOVAL", "START_BACKFILL", "SUBMIT_FINAL_REVIEW")


@bp.post("/demolition/projects")
@require_roles("ContractorAdmin")
def create_project():
    b = body()
    name = req_str(b, "name")
    address = req_str(b, "address")
    lot_area = req_int(b, "lot_area_sqft", minimum=1)
    rdr = opt_number(b, "required_diversion_rate")
    if rdr is None:
        rdr = Decimal("0.5")
    elif rdr < 0 or rdr > 1:
        raise err(ERR_VALIDATION, "required_diversion_rate must be in [0,1]")
    blackout = b.get("blackout_dates", [])
    if blackout is None:
        blackout = []
    if not isinstance(blackout, list) or not all(is_date_str(x) for x in blackout):
        raise err(ERR_VALIDATION, "blackout_dates must be an array of YYYY-MM-DD dates")

    rec = new_record()
    rec.update({
        "name": name,
        "address": address,
        "lot_area_sqft": lot_area,
        "required_diversion_rate": rdr,
        "blackout_dates": list(blackout),
        "status": "DRAFT",
        "work_posture": "WORKABLE",
        "pinned_engineering_survey_id": None,
        "pinned_engineering_revision": None,
        "cumulative_exposure_score": Decimal("0"),
        "in_transit_tons": Decimal("0"),
        "landfill_tons": Decimal("0"),
        "diverted_tons": Decimal("0"),
        "removed_tons": Decimal("0"),
        "diversion_rate": Decimal("0"),
        "diversion_tier": "STANDARD",
    })
    store.projects[rec["id"]] = rec
    return success(ser_project(rec), status=201)


@bp.get("/demolition/projects")
@require_roles(*ALL_ROLES)
def list_projects():
    items = list(store.projects.values())
    status_arg = request.args.get("status")
    pin_arg = request.args.get("pinned_engineering_survey_id")
    if status_arg is not None:
        items = [p for p in items if p["status"] == status_arg]
    if pin_arg is not None:
        items = [p for p in items if p["pinned_engineering_survey_id"] == pin_arg]
    return list_response(items, ser_project)


@bp.get("/demolition/projects/<pid>")
@require_roles(*ALL_ROLES)
def get_one_project(pid):
    return success(ser_project(get_project(pid)))


def _require_workable(project):
    if project["work_posture"] != "WORKABLE":
        raise err(ERR_PROJECT_STOPPED, "project work_posture is STOPPED")


def _require_active_permit(project):
    current = now()
    for perm in project_permits(project["id"]):
        if perm["status"] == "ACTIVE" and perm["expires_at"] > current:
            return
    raise err(ERR_PERMIT_NOT_ACTIVE, "no ACTIVE unexpired permit for the project")


@bp.post("/demolition/projects/<pid>/transition")
@require_roles("SiteSupervisor")
def project_transition(pid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in PHASE_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    if "note" in b and b["note"] is not None and not isinstance(b["note"], str):
        raise err(ERR_VALIDATION, "note must be a string")
    project = get_project(pid)
    status = project["status"]

    if action == "START_DEMOLITION":
        if status != "RELEASED":
            raise err(ERR_INVALID_STATE, "START_DEMOLITION requires RELEASED")
        _require_workable(project)
        _require_active_permit(project)
        if notification_wait_window_open(project["id"], now()):
            raise err(ERR_NOTIFICATION_WINDOW_OPEN, "notification wait window still open")
        project["status"] = "DEMOLITION_ACTIVE"
    elif action == "COMPLETE_STRUCTURE_REMOVAL":
        if status != "DEMOLITION_ACTIVE":
            raise err(ERR_INVALID_STATE, "COMPLETE_STRUCTURE_REMOVAL requires DEMOLITION_ACTIVE")
        _require_workable(project)
        project["status"] = "DEBRIS_CLEARANCE"
    elif action == "START_BACKFILL":
        if status != "DEBRIS_CLEARANCE":
            raise err(ERR_INVALID_STATE, "START_BACKFILL requires DEBRIS_CLEARANCE")
        _require_workable(project)
        if not any(bp["status"] in BACKFILL_APPROVED_OR_LATER
                   for bp in project_backfill_plans(project["id"])):
            raise err(ERR_BACKFILL_NOT_APPROVED, "no approved-or-later backfill plan")
        project["status"] = "BACKFILL_PHASE"
    else:  # SUBMIT_FINAL_REVIEW
        if status != "BACKFILL_PHASE":
            raise err(ERR_INVALID_STATE, "SUBMIT_FINAL_REVIEW requires BACKFILL_PHASE")
        _require_workable(project)
        project["status"] = "FINAL_REVIEW"

    touch(project)
    return success(ser_project(project))


@bp.post("/demolition/projects/<pid>/release")
@require_roles("SiteSupervisor", "ContractorAdmin")
def release_project(pid):
    b = body()
    if "note" in b and b["note"] is not None and not isinstance(b["note"], str):
        raise err(ERR_VALIDATION, "note must be a string")
    project = get_project(pid)
    if project["status"] != "PRECONDITIONS_PENDING":
        raise err(ERR_INVALID_STATE, "release requires PRECONDITIONS_PENDING")
    _require_workable(project)

    # Release prerequisite chain, in the fixed PRD §3.7 order.
    surveys = project_surveys(project["id"])
    if not surveys or any(s["status"] != "COMPLETE" for s in surveys):
        raise err(ERR_SURVEY_INCOMPLETE, "all structure surveys must be COMPLETE")
    if any(a["status"] != "CLEARANCE_CERTIFIED" for a in project_abatements(project["id"])):
        raise err(ERR_HAZMAT_UNRESOLVED, "an abatement order is outside CLEARANCE_CERTIFIED")
    disconnects = project_disconnects(project["id"])
    if not disconnects or any(
            u["disconnect_status"] != "REPORTED_DISCONNECTED" or u["verification_status"] != "CONFIRMED"
            for u in disconnects):
        raise err(ERR_UTILITY_UNVERIFIED, "utility disconnects missing or unconfirmed")
    _require_active_permit(project)
    pin_id = project["pinned_engineering_survey_id"]
    survey = store.engineering_surveys.get(pin_id) if pin_id else None
    if survey is None or survey["status"] != "CERTIFIED":
        raise err(ERR_ENGINEERING_NOT_CERTIFIED, "pinned engineering survey missing or not CERTIFIED")
    notifications = project_notifications(project["id"])
    delivered = [n for n in notifications if n["status"] == "DELIVERED"]
    pending = [n for n in notifications if n["status"] == "PENDING_DELIVERY"]
    if not notifications or pending or not delivered:
        raise err(ERR_NOTIFICATIONS_INCOMPLETE, "notifications missing or not all DELIVERED")
    if notification_wait_window_open(project["id"], now()):
        raise err(ERR_NOTIFICATION_WINDOW_OPEN, "72h wait window not yet elapsed")
    if survey["revision_number"] != project["pinned_engineering_revision"]:
        raise err(ERR_ENGINEERING_PIN_STALE, "pinned revision is stale")

    project["status"] = "RELEASED"
    touch(project)
    return success(ser_project(project))


@bp.post("/demolition/projects/<pid>/resume")
@require_roles("SiteSupervisor")
def resume_project(pid):
    b = body()
    if "note" in b and b["note"] is not None and not isinstance(b["note"], str):
        raise err(ERR_VALIDATION, "note must be a string")
    project = get_project(pid)
    if project["work_posture"] != "STOPPED":
        raise err(ERR_INVALID_STATE, "project is not STOPPED")
    project["work_posture"] = "WORKABLE"
    touch(project)
    return success(ser_project(project))


@bp.post("/demolition/projects/<pid>/engineering-pin")
@require_roles("SiteSupervisor")
def pin_engineering(pid):
    b = body()
    survey_id = req_str(b, "engineering_survey_id")
    expected_version = req_int(b, "expected_project_version")
    project = get_project(pid)
    survey = store.engineering_surveys.get(survey_id)
    if survey is None or survey["project_id"] != project["id"]:
        raise err(ERR_NOT_FOUND, "engineering survey not found for this project")
    if project["status"] not in ("PRECONDITIONS_PENDING", "RELEASED"):
        raise err(ERR_INVALID_STATE, "pinning requires PRECONDITIONS_PENDING or RELEASED")
    if expected_version != project["version"]:
        raise err(ERR_STALE_VERSION, "expected_project_version is stale")
    if survey["status"] != "CERTIFIED":
        raise err(ERR_ENGINEERING_NOT_CERTIFIED, "engineering survey is not CERTIFIED")
    project["pinned_engineering_survey_id"] = survey["id"]
    project["pinned_engineering_revision"] = survey["revision_number"]
    touch(project)
    return success(ser_project(project))
