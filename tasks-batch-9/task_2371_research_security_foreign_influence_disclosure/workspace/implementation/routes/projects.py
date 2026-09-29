"""Sponsored projects: creation, funding dimension, security dimension."""

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import RSO, SYSTEM_ADMIN, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("projects", __name__)

AWARD_TRANSITIONS = {
    "PROPOSED": ("ACTIVATION_PENDING", "WITHDRAWN"),
    "ACTIVATION_PENDING": ("ACTIVE", "WITHDRAWN"),
    "ACTIVE": ("CLOSED",),
    "CLOSED": (),
    "WITHDRAWN": (),
}

SECURITY_TRANSITIONS = {
    "PENDING_CLEARANCE": ("CLEARED",),
    "CLEARED": ("SUSPENDED", "TERMINATED"),
    "SUSPENDED": ("CLEARED", "TERMINATED"),
    "TERMINATED": (),
}


@bp.post("/projects")
def create_project():
    require(SYSTEM_ADMIN)
    data = validate.body()

    title = validate.req_string(data, "title")
    agency_code = validate.req_enum(data, "agency_code", E.AGENCY_CODES)
    sensitivity_level = validate.req_enum(data, "sensitivity_level",
                                          E.SENSITIVITY_LEVELS)
    award_amount_cents = validate.req_int(data, "award_amount_cents", minimum=0)
    period_start = validate.req_instant(data, "period_start")
    period_end = validate.req_instant(data, "period_end")
    capacity = validate.opt_int(data, "controlled_area_capacity", minimum=0,
                               default=0)

    # step 17 — interval sanity
    if util.parse_dt(period_end) <= util.parse_dt(period_start):
        raise ApiError("ERR_INVALID_PERIOD",
                       "period_end must be strictly after period_start.")

    record = db.base_record()
    record.update({
        "title": title,
        "agency_code": agency_code,
        "sensitivity_level": sensitivity_level,
        "award_amount_cents": award_amount_cents,
        "period_start": period_start,
        "period_end": period_end,
        "controlled_area_capacity": capacity,
        "award_status": "PROPOSED",
        "security_status": "PENDING_CLEARANCE",
        "security_status_reason": "NONE",
        "activation_blockers": [],
        "active_grant_count": 0,
        "controlled_area_posture": "LOCKED_DOWN",
        "open_incident_count": 0,
    })
    db.projects[record["id"]] = record
    derive.compute_project(record)
    return response.object_response(present.project(record), 201)


@bp.get("/projects/<project_id>")
def read_project(project_id):
    require_any()
    record = must_exist("project", project_id)
    return response.object_response(present.project(record))


@bp.get("/projects")
def list_projects():
    require_any()
    agency_code = validate.filter_enum("agency_code", E.AGENCY_CODES)
    award_status = validate.filter_enum("award_status", E.AWARD_STATUSES)
    security_status = validate.filter_enum("security_status", E.SECURITY_STATUSES)
    sensitivity = validate.filter_enum("sensitivity_level", E.SENSITIVITY_LEVELS)

    rows = []
    for record in db.ordered(db.projects.values()):
        if agency_code and record["agency_code"] != agency_code:
            continue
        if award_status and record["award_status"] != award_status:
            continue
        if security_status and record["security_status"] != security_status:
            continue
        if sensitivity and record["sensitivity_level"] != sensitivity:
            continue
        rows.append(record)
    return render_list(rows, present.project)


# ------------------------------------------------------------ funding dimension

@bp.post("/projects/<project_id>/award-status")
def set_award_status(project_id):
    require(SYSTEM_ADMIN)
    data = validate.body()
    project = must_exist("project", project_id)

    to_status = validate.req_enum(data, "to_status", E.AWARD_STATUSES)
    current = project["award_status"]
    if to_status not in AWARD_TRANSITIONS[current]:
        raise ApiError("ERR_INVALID_PROJECT_TRANSITION",
                       "Award status cannot move %s -> %s." % (current, to_status))

    if to_status == "ACTIVATION_PENDING":
        if not any(p["role_on_project"] == "PI" and p["status"] == "ACTIVE"
                   for p in derive.project_personnel(project_id)):
            raise ApiError("ERR_PI_REQUIRED",
                           "An ACTIVE PI personnel row is required.")
        project["award_status"] = to_status
        db.touch(project)
        cascade.recompute_project(project)

    elif to_status == "ACTIVE":
        blockers = derive.activation_blockers(project)
        if blockers:
            raise ApiError("ERR_ACTIVATION_BLOCKED",
                           "Activation is blocked by %s." % blockers[0])
        project["award_status"] = to_status
        db.touch(project)
        cascade.recompute_project(project)

    elif to_status == "CLOSED":
        if any(g["status"] in ("REQUESTED", "ACTIVE", "SUSPENDED")
               for g in derive.project_grants(project_id)):
            raise ApiError("ERR_ACCESS_GRANTS_OPEN",
                           "Every access grant must be REVOKED before closure.")
        if derive.open_incident_count(project_id) != 0:
            raise ApiError("ERR_OPEN_INCIDENTS",
                           "Open security incidents remain on this project.")
        project["award_status"] = to_status
        db.touch(project)
        cascade.terminate_project_subawards(project)
        _remove_personnel(project, ("ACTIVE",))
        cascade.recompute_project(project)

    else:  # WITHDRAWN
        project["award_status"] = to_status
        db.touch(project)
        cascade.terminate_project_subawards(project)
        _remove_personnel(project, ("PROPOSED", "ACTIVE"))
        cascade.recompute_project(project)

    return response.object_response(present.project(project))


def _remove_personnel(project, statuses):
    for row in derive.project_personnel(project["id"]):
        if row["status"] not in statuses:
            continue
        was_active = row["status"] == "ACTIVE"
        row["status"] = "REMOVED"
        db.touch(row)
        if was_active:
            cascade.recompute_investigator_by_id(row["investigator_id"])


# ----------------------------------------------------------- security dimension

@bp.post("/projects/<project_id>/security-status")
def set_security_status(project_id):
    require(RSO)
    data = validate.body()
    project = must_exist("project", project_id)

    to_status = validate.req_enum(data, "to_status", E.SECURITY_STATUSES)
    current = project["security_status"]
    if to_status not in SECURITY_TRANSITIONS[current]:
        raise ApiError("ERR_INVALID_PROJECT_TRANSITION",
                       "Security status cannot move %s -> %s."
                       % (current, to_status))

    if to_status == "CLEARED":
        # step 11 (posture) precedes step 12 (subaward screening) per PRD 2.8
        for row in derive.project_personnel(project_id):
            if row["status"] != "ACTIVE":
                continue
            investigator = db.investigators.get(row["investigator_id"])
            if investigator is not None and \
                    derive.posture_of(investigator) == "SUSPENDED":
                raise ApiError("ERR_INVESTIGATOR_SUSPENDED",
                               "An ACTIVE investigator on this project is SUSPENDED.")
        if any(s["status"] in ("PENDING", "FLAGGED", "BLOCKED")
               for s in derive.project_subawards(project_id)):
            raise ApiError("ERR_SUBAWARD_SCREENING_OPEN",
                           "A subaward on this project is still unresolved.")
        if current == "SUSPENDED" and derive.open_incident_count(project_id) != 0:
            raise ApiError("ERR_OPEN_INCIDENTS",
                           "Open security incidents remain on this project.")

        project["security_status"] = "CLEARED"
        project["security_status_reason"] = "OFFICER_ACTION"
        db.touch(project)
        if current == "SUSPENDED":
            cascade.restore_project_grants(project)
        cascade.recompute_project(project)

    elif to_status == "SUSPENDED":
        project["security_status"] = "SUSPENDED"
        project["security_status_reason"] = "OFFICER_ACTION"
        db.touch(project)
        cascade.suspend_project_grants(project, "PROJECT_SUSPENDED")
        cascade.recompute_project(project)

    else:  # TERMINATED
        project["security_status"] = "TERMINATED"
        db.touch(project)
        cascade.revoke_project_grants(project, "PROJECT_TERMINATED")
        cascade.terminate_project_subawards(project)
        cascade.recompute_project(project)

    return response.object_response(present.project(project))
