"""Project personnel rosters and the effort ledger (PRD 3.2)."""

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import RSO, SYSTEM_ADMIN, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("personnel", __name__)

PERSONNEL_TRANSITIONS = {
    "PROPOSED": ("ACTIVE", "REMOVED"),
    "ACTIVE": ("REMOVED",),
    "REMOVED": (),
}


@bp.post("/projects/<project_id>/personnel")
def create_personnel(project_id):
    require(SYSTEM_ADMIN)
    data = validate.body()
    project = must_exist("project", project_id)

    investigator = must_exist("investigator", data.get("investigator_id"))
    role_on_project = validate.req_enum(data, "role_on_project", E.PROJECT_ROLES)
    months = validate.req_decimal(data, "committed_person_months",
                                  exclusive_min=0, maximum=12, max_places=2)

    record = db.base_record()
    record.update({
        "project_id": project["id"],
        "investigator_id": investigator["id"],
        "role_on_project": role_on_project,
        "committed_person_months": months,
        "status": "PROPOSED",
    })
    db.personnel[record["id"]] = record
    cascade.recompute_project(project)
    return response.object_response(present.personnel(record), 201)


@bp.get("/project-personnel/<personnel_id>")
def read_personnel(personnel_id):
    require_any()
    record = must_exist("personnel", personnel_id)
    return response.object_response(present.personnel(record))


@bp.get("/project-personnel")
def list_personnel():
    require_any()
    project_id = validate.filter_value("project_id")
    investigator_id = validate.filter_value("investigator_id")
    status = validate.filter_enum("status", E.PERSONNEL_STATUSES)

    rows = []
    for record in db.ordered(db.personnel.values()):
        if project_id and record["project_id"] != project_id:
            continue
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.personnel)


@bp.post("/project-personnel/<personnel_id>/status")
def set_personnel_status(personnel_id):
    require(SYSTEM_ADMIN, RSO)
    data = validate.body()
    record = must_exist("personnel", personnel_id)

    to_status = validate.req_enum(data, "to_status", E.PERSONNEL_STATUSES)
    current = record["status"]
    if to_status not in PERSONNEL_TRANSITIONS[current]:
        raise ApiError("ERR_INVALID_PERSONNEL_TRANSITION",
                       "Personnel status cannot move %s -> %s."
                       % (current, to_status))

    project = db.projects.get(record["project_id"])
    investigator = db.investigators.get(record["investigator_id"])

    if to_status == "ACTIVE":
        if investigator is not None and \
                derive.posture_of(investigator) == "SUSPENDED":
            raise ApiError("ERR_INVESTIGATOR_SUSPENDED",
                           "A SUSPENDED investigator cannot be activated.")
        if project is not None and project["award_status"] not in (
                "PROPOSED", "ACTIVATION_PENDING", "ACTIVE"):
            raise ApiError("ERR_INVALID_PROJECT_TRANSITION",
                           "A %s award takes on no new active personnel."
                           % project["award_status"])
        if investigator is not None:
            plan = derive.active_plan_credit_disclosure(investigator["id"])
            if plan is not None and plan.get("plan_effort_cap_pct") is not None:
                projected = derive.projected_total_commitment(
                    investigator, record["committed_person_months"])
                if projected > util.dec(plan["plan_effort_cap_pct"]):
                    raise ApiError("ERR_EFFORT_CAP_EXCEEDED",
                                   "Total commitment would exceed the plan cap.")
        record["status"] = "ACTIVE"
        db.touch(record)
        cascade.recompute_investigator(investigator)
        cascade.recompute_project(project)

    elif current == "ACTIVE":  # ACTIVE -> REMOVED
        record["status"] = "REMOVED"
        db.touch(record)
        cascade.recompute_investigator(investigator)
        cascade.revoke_personnel_grants(record["project_id"],
                                        record["investigator_id"])
        cascade.recompute_project(project)

    else:  # PROPOSED -> REMOVED, no effort recompute at all
        record["status"] = "REMOVED"
        db.touch(record)
        cascade.recompute_project(project)

    return response.object_response(present.personnel(record))
