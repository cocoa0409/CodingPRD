"""InstallationActivity routes: create, release, complete, cancel."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, PROJECT_ENGINEER, PROJECT_MANAGER, require_roles
from db import store
from errors import (
    activity_not_found,
    activity_not_planned,
    activity_not_released,
    crew_window_conflict,
    invalid_date_range,
    long_lead_not_delivered,
    open_rfi_blocks_release,
    project_not_found,
    subcontractor_not_found,
    submittal_not_found,
    submittal_not_released,
)
from respond import success
from serialize import ser_activity
from services import find_lli_for_submittal, require_active
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_str,
    paginate,
    req_date,
    req_str,
    sorted_by_creation,
    touch,
)

bp = Blueprint("installation_activities", __name__)


def get_activity_or_404(activity_id):
    a = store.installation_activities.get(activity_id)
    if a is None:
        raise activity_not_found()
    return a


@bp.route("/v1/projects/<projectId>/installation-activities", methods=["POST"])
def create_activity(projectId):
    require_roles([PROJECT_ENGINEER])
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    require_active(project)
    data = json_body()
    submittal_id = req_str(data, "submittal_id")
    subcontractor_id = req_str(data, "subcontractor_id")
    description = opt_str(data, "description", "")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")

    submittal = store.submittals.get(submittal_id)
    if submittal is None or submittal["project_id"] != projectId:
        raise submittal_not_found()
    sub_entity = store.subcontractors.get(subcontractor_id)
    if sub_entity is None or sub_entity["project_id"] != projectId:
        raise subcontractor_not_found()

    if end_date <= start_date:
        raise invalid_date_range("end_date must be strictly later than start_date")

    candidate = {
        "subcontractor_id": subcontractor_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if calc.crew_window_conflict(project, candidate):
        raise crew_window_conflict()

    activity = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_id": projectId,
        "submittal_id": submittal_id,
        "subcontractor_id": subcontractor_id,
        "description": description,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PLANNED",
        "shift_applied_days": 0,
    }
    store.installation_activities[activity["id"]] = activity
    return success(ser_activity(activity), status=201)


@bp.route("/v1/projects/<projectId>/installation-activities", methods=["GET"])
def list_project_activities(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [a for a in store.installation_activities.values() if a["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_activity(a) for a in page], response_type="array", pagination=pagination)


@bp.route("/v1/installation-activities", methods=["GET"])
def list_activities():
    require_roles(ALL_ROLES)
    items = list(store.installation_activities.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [a for a in items if a["project_id"] == project_id]
    submittal_id = request.args.get("submittal_id")
    if submittal_id:
        items = [a for a in items if a["submittal_id"] == submittal_id]
    subcontractor_id = request.args.get("subcontractor_id")
    if subcontractor_id:
        items = [a for a in items if a["subcontractor_id"] == subcontractor_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_activity(a) for a in page], response_type="array", pagination=pagination)


@bp.route("/v1/installation-activities/<activityId>", methods=["GET"])
def get_activity(activityId):
    require_roles(ALL_ROLES)
    act = get_activity_or_404(activityId)
    return success(ser_activity(act))


@bp.route("/v1/installation-activities/<activityId>/release", methods=["POST"])
def release_activity(activityId):
    require_roles([PROJECT_MANAGER])
    act = get_activity_or_404(activityId)
    project = store.projects.get(act["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if act["status"] != "PLANNED":
        raise activity_not_planned()
    # Temporal: crew window re-check
    candidate = {
        "subcontractor_id": act["subcontractor_id"],
        "start_date": act["start_date"],
        "end_date": act["end_date"],
    }
    if calc.crew_window_conflict(project, candidate, exclude_id=act["id"]):
        raise crew_window_conflict()
    # Referential gates
    submittal = store.submittals.get(act["submittal_id"])
    if submittal is None:
        raise submittal_not_found()
    if submittal["review_status"] not in ("RELEASED", "DISTRIBUTED", "CLOSED"):
        raise submittal_not_released()
    for r in store.rfis.values():
        if r["project_id"] == project["id"] and r.get("submittal_id") == submittal["id"]:
            if r["status"] in ("OPEN", "ROUTED"):
                raise open_rfi_blocks_release()
    if submittal["is_long_lead"]:
        lli = find_lli_for_submittal(submittal["id"])
        if lli is None or lli["status"] != "DELIVERED":
            raise long_lead_not_delivered()
    act["status"] = "RELEASED"
    touch(act)
    return success(ser_activity(act))


@bp.route("/v1/installation-activities/<activityId>/complete", methods=["POST"])
def complete_activity(activityId):
    require_roles([PROJECT_ENGINEER])
    act = get_activity_or_404(activityId)
    project = store.projects.get(act["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if act["status"] != "RELEASED":
        raise activity_not_released()
    act["status"] = "COMPLETED"
    touch(act)
    return success(ser_activity(act))


@bp.route("/v1/installation-activities/<activityId>/cancel", methods=["POST"])
def cancel_activity(activityId):
    require_roles([PROJECT_MANAGER])
    act = get_activity_or_404(activityId)
    project = store.projects.get(act["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    if act["status"] not in ("PLANNED", "RELEASED"):
        raise activity_not_planned()
    act["status"] = "CANCELLED"
    touch(act)
    return success(ser_activity(act))
