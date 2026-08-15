from flask import Blueprint, request

from db import store, now
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_enum,
    f_dt,
    ok,
    paginate,
)
from errors import ApiError
from services import get_project, get_inspection, new_entity, ser_inspection, bump

bp = Blueprint("inspections", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)

INSPECTION_TYPES = {"DAILY", "WEEKLY", "QUARTERLY_REGULATORY"}


@bp.route("/safety/inspections", methods=["POST"])
def create_inspection():
    require_roles("SafetyInspector")
    b = body()
    raw_pid = b.get("project_id")
    if isinstance(raw_pid, str):
        get_project(raw_pid)
    reject_unknown(b, {"project_id", "inspection_type", "due_date"})
    project_id = f_str(b, "project_id")
    get_project(project_id)
    inspection_type = f_enum(b, "inspection_type", INSPECTION_TYPES)
    due_date = f_dt(b, "due_date")
    i = new_entity()
    i.update(
        {
            "project_id": project_id,
            "inspection_type": inspection_type,
            "due_date": due_date,
            "status": "DUE",
            "completed_at": None,
            "findings_summary": "",
        }
    )
    store.inspections[i["id"]] = i
    return ok(ser_inspection(i), 201)


@bp.route("/safety/inspections", methods=["GET"])
def list_inspections():
    require_roles(*ALL_ROLES)
    records = list(store.inspections.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [i for i in records if i["project_id"] == pid]
    itype = request.args.get("inspection_type")
    if itype is not None:
        records = [i for i in records if i["inspection_type"] == itype]
    status = request.args.get("status")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    return paginate(records, ser_inspection)


@bp.route("/safety/inspections/<inspectionId>", methods=["GET"])
def get_one_inspection(inspectionId):
    require_roles(*ALL_ROLES)
    return ok(ser_inspection(get_inspection(inspectionId)))


@bp.route("/safety/inspections/<inspectionId>/complete", methods=["POST"])
def complete_inspection(inspectionId):
    require_roles("SafetyInspector")
    inspection = get_inspection(inspectionId)
    b = body()
    reject_unknown(b, {"findings_summary"})
    findings_summary = f_str(b, "findings_summary", required=False, default=None)
    if inspection["status"] not in ("DUE", "OVERDUE"):
        raise ApiError(
            "ERR_INSPECTION_INVALID_STATE",
            409,
            "complete requires status DUE or OVERDUE",
        )
    inspection["status"] = "COMPLETED"
    inspection["completed_at"] = now()
    if findings_summary is not None:
        inspection["findings_summary"] = findings_summary
    bump(inspection)
    return ok(ser_inspection(inspection))
