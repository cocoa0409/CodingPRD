"""Lesson routes: schedule (capacity + bay-window overlap), read/list,
complete, cancel (PRD §3.11; SCAFFOLD §1.5)."""

from flask import Blueprint, request

from db import db, stamp_common, touch
from clock import parse_iso
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles, require_owner
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_BAY_WINDOW_CONFLICT,
    ERR_BAY_UNAVAILABLE,
)
from services import validate as V
from services.lookup import get_or_404, bay_window_conflict
from services.serialize import lesson_out

bp = Blueprint("lessons", __name__)

KINDS = {"PRIVATE_LESSON", "GROUP_CLINIC", "SIMULATOR"}


@bp.post("/golf/lessons")
def create_lesson():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk"})
    data = V.body()

    venue_id = V.as_str(V.require(data, "venue_id"), "venue_id")
    bay_id = V.as_str(V.require(data, "bay_id"), "bay_id")
    member_id = V.as_str(V.require(data, "member_id"), "member_id")
    require_owner(caller, member_id)

    venue = get_or_404(db.venues, venue_id, "venue")
    bay = get_or_404(db.bays, bay_id, "bay")
    get_or_404(db.members, member_id, "member")

    kind = V.as_enum(V.require(data, "kind"), "kind", KINDS)
    start_raw = V.as_str(V.require(data, "start_utc"), "start_utc")
    end_raw = V.as_str(V.require(data, "end_utc"), "end_utc")
    seats = data.get("seats", 1)
    seats = V.int_min(seats, "seats", 1)

    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "start_utc/end_utc must be ISO 8601 instants")
    if end_dt <= start_dt:
        raise_err(ERR_INVALID_REQUEST, "end_utc must be after start_utc")

    # Bay-window overlap (priority 7).
    if bay_window_conflict(bay_id, start_dt, end_dt):
        raise_err(ERR_BAY_WINDOW_CONFLICT, "bay window overlaps a confirmed reservation or scheduled lesson")

    # Capacity + safety (priority 8): PRIVATE_LESSON / SIMULATOR capped at 1 seat;
    # OUT_OF_SERVICE bay rejected.
    if kind in ("PRIVATE_LESSON", "SIMULATOR") and seats > 1:
        raise_err(ERR_BAY_UNAVAILABLE, "this lesson kind is capped at a single seat")
    if bay["status"] == "OUT_OF_SERVICE":
        raise_err(ERR_BAY_UNAVAILABLE, "bay is out of service")

    lesson = stamp_common({
        "venue_id": venue_id,
        "bay_id": bay_id,
        "member_id": member_id,
        "kind": kind,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "seats": seats,
        "status": "SCHEDULED",
    })
    db.lessons[lesson["id"]] = lesson
    return success(lesson_out(lesson), status=201)


@bp.get("/golf/lessons/<lesson_id>")
def get_lesson(lesson_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    le = get_or_404(db.lessons, lesson_id, "lesson")
    return success(lesson_out(le))


@bp.get("/golf/lessons")
def list_lessons():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.lessons.values())
    for key in ("venue_id", "bay_id", "member_id"):
        val = request.args.get(key)
        if val is not None:
            records = [le for le in records if le.get(key) == val]
    window, total = paginate(records, limit, offset)
    return list_success([lesson_out(le) for le in window], limit, offset, total)


@bp.post("/golf/lessons/<lesson_id>/complete")
def complete_lesson(lesson_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    le = get_or_404(db.lessons, lesson_id, "lesson")
    V.body()
    if le["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "lesson is not SCHEDULED")
    le["status"] = "COMPLETED"
    touch(le)
    return success(lesson_out(le))


@bp.post("/golf/lessons/<lesson_id>/cancel")
def cancel_lesson(lesson_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk"})
    le = get_or_404(db.lessons, lesson_id, "lesson")
    require_owner(caller, le["member_id"])
    V.body()
    if le["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "lesson is not SCHEDULED")
    le["status"] = "CANCELLED"
    touch(le)
    return success(lesson_out(le))
