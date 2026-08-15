"""InterviewDay routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_season_posture_forbidden,
    err_day_state_forbidden,
    err_day_outside_window,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_interview_day,
    interview_day_view,
    interview_slot_view,
)
from utils import (
    parse_pagination,
    require_int,
    require_timestamp,
    stamp_new,
    touch,
)

bp = Blueprint("interview_days", __name__)


@bp.route("/seasons/<sid>/interview-days", methods=["POST"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def create_interview_day(sid):
    season = get_season(sid)
    payload = request.get_json(silent=True) or {}
    window_start_at = require_timestamp(payload, "window_start_at")
    window_end_at = require_timestamp(payload, "window_end_at")
    if window_end_at <= window_start_at:
        from errors import err_validation
        raise err_validation("window_end_at must be > window_start_at")
    capacity = require_int(payload, "capacity", min_value=1)
    # Posture gate
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    # Window containment
    if not (
        season["_interview_window_start_at"] <= window_start_at
        and window_end_at <= season["_interview_window_end_at"]
    ):
        raise err_day_outside_window()
    d = {
        "season_id": sid,
        "_window_start_at": window_start_at,
        "_window_end_at": window_end_at,
        "capacity": capacity,
        "booked_count": 0,
        "status": "OPEN",
    }
    stamp_new(d)
    db.interview_days[d["id"]] = d
    return success_object(interview_day_view(d), 201)


@bp.route("/interview-days/<did>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def get_one_interview_day(did):
    d = get_interview_day(did)
    return success_object(interview_day_view(d))


@bp.route("/seasons/<sid>/interview-days", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_season_interview_days(sid):
    get_season(sid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        d for d in db.interview_days.values()
        if d["season_id"] == sid and (status is None or d["status"] == status)
    ]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([interview_day_view(d) for d in page], total, limit, offset)


@bp.route("/interview-days/<did>/lock", methods=["POST"])
@require_auth(["Recruiter"])
def lock_interview_day(did):
    d = get_interview_day(did)
    season = get_season(d["season_id"])
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    if d["status"] != "OPEN":
        raise err_day_state_forbidden("lock requires OPEN")
    d["status"] = "LOCKED"
    touch(d)
    return success_object(interview_day_view(d))


@bp.route("/interview-days/<did>/complete", methods=["POST"])
@require_auth(["Recruiter"])
def complete_interview_day(did):
    d = get_interview_day(did)
    # Day status gate: must be LOCKED with all slots terminal
    if d["status"] != "LOCKED":
        raise err_day_state_forbidden("complete requires LOCKED")
    slots = [s for s in db.interview_slots.values() if s["interview_day_id"] == did]
    for s in slots:
        if s["status"] not in ("COMPLETED", "CANCELLED", "NO_SHOW"):
            raise err_day_state_forbidden("All slots must be terminal to complete the day")
    d["status"] = "COMPLETED"
    touch(d)
    return success_object(interview_day_view(d))


@bp.route("/interview-days/<did>/interview-slots", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_day_slots(did):
    get_interview_day(did)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        s for s in db.interview_slots.values()
        if s["interview_day_id"] == did
        and (status is None or s["status"] == status)
    ]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([interview_slot_view(s) for s in page], total, limit, offset)
