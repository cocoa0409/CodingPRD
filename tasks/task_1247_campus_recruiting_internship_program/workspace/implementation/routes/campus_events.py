"""CampusEvent routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_validation,
    err_season_posture_forbidden,
    err_event_state_forbidden,
    err_event_time_overlap,
    err_school_dropped,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_school_target,
    get_campus_event,
    campus_event_view,
)
from utils import (
    parse_pagination,
    require_enum,
    require_timestamp,
    require_field,
    stamp_new,
    touch,
)

bp = Blueprint("campus_events", __name__)

EVENT_TYPES = {"CAREER_FAIR", "INFO_SESSION", "RESUME_DROP"}


@bp.route("/seasons/<sid>/campus-events", methods=["POST"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def create_campus_event(sid):
    season = get_season(sid)
    payload = request.get_json(silent=True) or {}
    school_target_id = require_field(payload, "school_target_id")
    if not isinstance(school_target_id, str):
        raise err_validation("school_target_id must be a string")
    event_type = require_enum(payload, "event_type", EVENT_TYPES)
    start_at = require_timestamp(payload, "start_at")
    end_at = require_timestamp(payload, "end_at")
    if end_at <= start_at:
        raise err_validation("end_at must be > start_at")
    # Posture gate
    if season["status"] not in ("OPEN", "SELECTION"):
        raise err_season_posture_forbidden()
    # School must exist and be ACTIVE
    school = get_school_target(school_target_id)
    # School must belong to this season (nested ownership)
    if school["season_id"] != sid:
        from errors import err_not_found
        raise err_not_found(f"SchoolTarget {school_target_id} not in season {sid}")
    if school["status"] != "ACTIVE":
        raise err_school_dropped()
    # Half-open overlap vs SCHEDULED/COMPLETED events of the SAME school
    for ev in db.campus_events.values():
        if ev["school_target_id"] != school_target_id:
            continue
        if ev["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        # half-open intersection: [start,end) intersects [s2,e2) iff start < e2 and s2 < end
        if start_at < ev["_end_at"] and ev["_start_at"] < end_at:
            raise err_event_time_overlap()
    e = {
        "season_id": sid,
        "school_target_id": school_target_id,
        "event_type": event_type,
        "_start_at": start_at,
        "_end_at": end_at,
        "status": "SCHEDULED",
        "resume_count": 0,
    }
    stamp_new(e)
    db.campus_events[e["id"]] = e
    return success_object(campus_event_view(e), 201)


@bp.route("/campus-events/<eid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def get_one_campus_event(eid):
    e = get_campus_event(eid)
    return success_object(campus_event_view(e))


@bp.route("/seasons/<sid>/campus-events", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_season_campus_events(sid):
    get_season(sid)
    limit, offset = parse_pagination(request.args)
    school_target_id = request.args.get("school_target_id")
    event_type = request.args.get("event_type")
    status = request.args.get("status")
    items = [
        e for e in db.campus_events.values()
        if e["season_id"] == sid
        and (school_target_id is None or e["school_target_id"] == school_target_id)
        and (event_type is None or e["event_type"] == event_type)
        and (status is None or e["status"] == status)
    ]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([campus_event_view(e) for e in page], total, limit, offset)


@bp.route("/school-targets/<tid>/campus-events", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_school_campus_events(tid):
    get_school_target(tid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        e for e in db.campus_events.values()
        if e["school_target_id"] == tid
        and (status is None or e["status"] == status)
    ]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([campus_event_view(e) for e in page], total, limit, offset)


@bp.route("/campus-events/<eid>/complete", methods=["POST"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def complete_campus_event(eid):
    e = get_campus_event(eid)
    season = get_season(e["season_id"])
    if season["status"] not in ("OPEN", "SELECTION"):
        raise err_season_posture_forbidden()
    if e["status"] != "SCHEDULED":
        raise err_event_state_forbidden()
    payload = request.get_json(silent=True) or {}
    rc = payload.get("resume_count")
    if rc is None:
        from errors import err_validation as ev
        raise ev("resume_count is required")
    if isinstance(rc, bool) or not isinstance(rc, int) or rc < 0:
        raise err_validation("resume_count must be an integer >= 0")
    e["resume_count"] = rc
    e["status"] = "COMPLETED"
    touch(e)
    return success_object(campus_event_view(e))


@bp.route("/campus-events/<eid>/cancel", methods=["POST"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def cancel_campus_event(eid):
    e = get_campus_event(eid)
    season = get_season(e["season_id"])
    if season["status"] not in ("OPEN", "SELECTION"):
        raise err_season_posture_forbidden()
    if e["status"] != "SCHEDULED":
        raise err_event_state_forbidden()
    e["status"] = "CANCELLED"
    touch(e)
    return success_object(campus_event_view(e))
