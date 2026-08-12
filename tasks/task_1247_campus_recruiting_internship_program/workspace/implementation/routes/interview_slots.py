"""InterviewSlot routes."""

from datetime import timedelta

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_forbidden,
    err_season_posture_forbidden,
    err_application_state_forbidden,
    err_day_state_forbidden,
    err_slot_state_forbidden,
    err_evaluator_conflict_of_interest,
    err_evaluator_not_calibrated,
    err_capability_missing,
    err_slot_outside_day_window,
    err_candidate_schedule_conflict,
    err_evaluator_schedule_conflict,
    err_day_at_capacity,
)
from middleware import require_auth
from response import success_object, success_list
from services.calculations import EVALUATOR_BUFFER_MINUTES
from services.domain import (
    get_season,
    get_application,
    get_school_target,
    get_employee,
    get_interview_day,
    get_interview_slot,
    interview_slot_view,
    auto_flip_application,
)
from utils import (
    parse_pagination,
    require_field,
    require_timestamp,
    stamp_new,
    touch,
)

bp = Blueprint("interview_slots", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [a_start,a_end) intersect [b_start,b_end)"""
    return a_start < b_end and b_start < a_end


def _gap_seconds(a_start, a_end, b_start, b_end):
    """gap = max(0, max(start2-end1, start1-end2)). Zero when intersecting."""
    if _intervals_overlap(a_start, a_end, b_start, b_end):
        return 0
    g1 = (b_start - a_end).total_seconds()
    g2 = (a_start - b_end).total_seconds()
    return max(0, max(g1, g2))


@bp.route("/interview-days/<did>/interview-slots", methods=["POST"])
@require_auth(["Recruiter"])
def book_slot(did):
    day = get_interview_day(did)
    season = get_season(day["season_id"])
    payload = request.get_json(silent=True) or {}
    application_id = require_field(payload, "application_id")
    evaluator_id = require_field(payload, "evaluator_id")
    start_at = require_timestamp(payload, "start_at")
    end_at = require_timestamp(payload, "end_at")
    if end_at <= start_at:
        raise err_validation("end_at must be > start_at")

    application = get_application(application_id)
    evaluator = get_employee(evaluator_id)
    school = get_school_target(application["school_target_id"])

    # Posture (priority 8)
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    # Application state (priority 11)
    if application["status"] not in ("SHORTLISTED", "INTERVIEW_SCHEDULED"):
        raise err_application_state_forbidden("slot booking requires SHORTLISTED or INTERVIEW_SCHEDULED")
    # Day state (priority 13)
    if day["status"] != "OPEN":
        raise err_day_state_forbidden("slot booking requires day OPEN")
    # Evaluator governance (priority 19, 20, 22)
    alma = (evaluator.get("alma_mater_school_name") or "").strip().lower()
    school_name = (school["school_name"] or "").strip().lower()
    if alma and school_name and alma == school_name:
        raise err_evaluator_conflict_of_interest()
    if school["tier"] == "CORE" and not evaluator["calibrated"]:
        raise err_evaluator_not_calibrated()
    if not evaluator["can_evaluate"]:
        raise err_capability_missing("can_evaluate is required")
    # Temporal containment (priority 25)
    if not (day["_window_start_at"] <= start_at and end_at <= day["_window_end_at"]):
        raise err_slot_outside_day_window()
    # Candidate schedule overlap (priority 37): half-open vs BOOKED slots of same application (any day)
    for s in db.interview_slots.values():
        if s["application_id"] != application_id:
            continue
        if s["status"] != "BOOKED":
            continue
        if _intervals_overlap(start_at, end_at, s["_start_at"], s["_end_at"]):
            raise err_candidate_schedule_conflict()
    # Evaluator buffered overlap (priority 38): vs BOOKED/COMPLETED slots on the same day
    buffer_seconds = EVALUATOR_BUFFER_MINUTES * 60
    for s in db.interview_slots.values():
        if s["evaluator_id"] != evaluator_id:
            continue
        if s["interview_day_id"] != did:
            continue
        if s["status"] not in ("BOOKED", "COMPLETED"):
            continue
        g = _gap_seconds(start_at, end_at, s["_start_at"], s["_end_at"])
        if g < buffer_seconds:
            raise err_evaluator_schedule_conflict()
    # Capacity (priority 39)
    if day["booked_count"] >= day["capacity"]:
        raise err_day_at_capacity("day booked_count reached capacity")
    evaluator_day_load = sum(
        1 for s in db.interview_slots.values()
        if s["evaluator_id"] == evaluator_id
        and s["interview_day_id"] == did
        and s["status"] in ("BOOKED", "COMPLETED")
    )
    if evaluator_day_load >= evaluator["daily_slot_limit"]:
        raise err_day_at_capacity("evaluator daily_slot_limit reached")

    slot = {
        "interview_day_id": did,
        "application_id": application_id,
        "evaluator_id": evaluator_id,
        "_start_at": start_at,
        "_end_at": end_at,
        "status": "BOOKED",
    }
    stamp_new(slot)
    db.interview_slots[slot["id"]] = slot
    day["booked_count"] += 1
    touch(day)
    if application["status"] == "SHORTLISTED":
        application["status"] = "INTERVIEW_SCHEDULED"
        touch(application)
    return success_object(interview_slot_view(slot), 201)


@bp.route("/interview-slots/<sid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Evaluator"])
def get_one_slot(sid):
    s = get_interview_slot(sid)
    if g.role == "Evaluator" and g.user_id != s["evaluator_id"]:
        raise err_forbidden("Evaluator may read only its own slots")
    return success_object(interview_slot_view(s))


@bp.route("/interview-slots/<sid>/cancel", methods=["POST"])
@require_auth(["Recruiter"])
def cancel_slot(sid):
    s = get_interview_slot(sid)
    day = get_interview_day(s["interview_day_id"])
    season = get_season(day["season_id"])
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    if day["status"] != "OPEN":
        raise err_day_state_forbidden("cancel requires day OPEN")
    if s["status"] != "BOOKED":
        raise err_slot_state_forbidden()
    s["status"] = "CANCELLED"
    touch(s)
    day["booked_count"] -= 1
    touch(day)
    application = get_application(s["application_id"])
    auto_flip_application(application)
    return success_object(interview_slot_view(s))


@bp.route("/interview-slots/<sid>/no-show", methods=["POST"])
@require_auth(["Recruiter"])
def no_show_slot(sid):
    s = get_interview_slot(sid)
    day = get_interview_day(s["interview_day_id"])
    season = get_season(day["season_id"])
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    if day["status"] not in ("OPEN", "LOCKED"):
        raise err_day_state_forbidden("no-show requires day OPEN or LOCKED")
    if s["status"] != "BOOKED":
        raise err_slot_state_forbidden()
    s["status"] = "NO_SHOW"
    touch(s)
    # booked_count unchanged (no-show consumes the seat)
    application = get_application(s["application_id"])
    auto_flip_application(application)
    return success_object(interview_slot_view(s))


@bp.route("/applications/<aid>/interview-slots", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def list_application_slots(aid):
    a = get_application(aid)
    if g.role == "Candidate" and g.user_id != a["candidate_id"]:
        raise err_forbidden("Candidate may read only its own slots")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [
        s for s in db.interview_slots.values()
        if s["application_id"] == aid
        and (status is None or s["status"] == status)
    ]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([interview_slot_view(s) for s in page], total, limit, offset)
