from flask import Blueprint, request

from db import store, now
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_date,
    f_list_str,
    ok,
    paginate,
)
from errors import ApiError
from services import get_project, get_huddle, new_entity, ser_huddle, bump

bp = Blueprint("huddles", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)


@bp.route("/safety/huddles", methods=["POST"])
def create_huddle():
    require_roles("SiteSuperintendent")
    b = body()
    raw_pid = b.get("project_id")
    if isinstance(raw_pid, str):
        get_project(raw_pid)
    reject_unknown(b, {"project_id", "huddle_date", "topics"})
    project_id = f_str(b, "project_id")
    get_project(project_id)
    huddle_date = f_date(b, "huddle_date")
    topics = f_str(b, "topics")
    # priority 9 (a): at most one huddle per (project_id, huddle_date)
    for h in store.huddles.values():
        if h["project_id"] == project_id and h["huddle_date"] == huddle_date:
            raise ApiError(
                "ERR_HUDDLE_ALREADY_EXISTS",
                409,
                "A Huddle already exists for this (project_id, huddle_date)",
            )
    h = new_entity()
    h.update(
        {
            "project_id": project_id,
            "huddle_date": huddle_date,
            "topics": topics,
            "status": "SCHEDULED",
            "attendee_worker_ids": [],
            "conducted_at": None,
        }
    )
    store.huddles[h["id"]] = h
    return ok(ser_huddle(h), 201)


@bp.route("/safety/huddles", methods=["GET"])
def list_huddles():
    require_roles(*ALL_ROLES)
    records = list(store.huddles.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [h for h in records if h["project_id"] == pid]
    hd = request.args.get("huddle_date")
    if hd is not None:
        records = [h for h in records if h["huddle_date"].isoformat() == hd]
    status = request.args.get("status")
    if status is not None:
        records = [h for h in records if h["status"] == status]
    return paginate(records, ser_huddle)


@bp.route("/safety/huddles/<huddleId>", methods=["GET"])
def get_one_huddle(huddleId):
    require_roles(*ALL_ROLES)
    return ok(ser_huddle(get_huddle(huddleId)))


@bp.route("/safety/huddles/<huddleId>/conduct", methods=["POST"])
def conduct_huddle(huddleId):
    require_roles("SiteSuperintendent")
    huddle = get_huddle(huddleId)
    b = body()
    # priority 3: attendee worker ids must exist and belong to this project
    raw_attendees = b.get("attendee_worker_ids")
    if isinstance(raw_attendees, list):
        for wid in raw_attendees:
            if not isinstance(wid, str):
                continue
            w = store.workers.get(wid)
            if w is None or w["project_id"] != huddle["project_id"]:
                raise ApiError(
                    "ERR_WORKER_NOT_FOUND", 404, "No Worker with the given id"
                )
    # priority 4: shape
    reject_unknown(b, {"attendee_worker_ids"})
    attendee_worker_ids = f_list_str(b, "attendee_worker_ids")
    for wid in attendee_worker_ids:
        w = store.workers.get(wid)
        if w is None or w["project_id"] != huddle["project_id"]:
            raise ApiError("ERR_WORKER_NOT_FOUND", 404, "No Worker with the given id")
    # priority 5: state
    if huddle["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_HUDDLE_INVALID_STATE", 409, "conduct requires status SCHEDULED"
        )
    # priority 7 (f): every attendee ORIENTED or CLEARED
    for wid in attendee_worker_ids:
        w = store.workers[wid]
        if w["status"] not in ("ORIENTED", "CLEARED"):
            raise ApiError(
                "ERR_WORKER_NOT_CLEARED",
                409,
                "Huddle attendees must be ORIENTED or CLEARED",
            )
    huddle["status"] = "CONDUCTED"
    huddle["attendee_worker_ids"] = list(attendee_worker_ids)
    huddle["conducted_at"] = now()
    bump(huddle)
    return ok(ser_huddle(huddle))
