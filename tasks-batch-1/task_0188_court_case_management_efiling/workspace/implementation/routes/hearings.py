"""Hearings."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc

bp = Blueprint("hearings", __name__)


def _overlaps(start_a, end_a, start_b, end_b):
    # Half-open overlap: two windows conflict if one starts before the other ends.
    return start_a < end_b and start_b < end_a


def _check_conflict(courtroom, judge_user_id, start_at, end_at, exclude_id=None):
    s = calc.parse_dt(start_at)
    e = calc.parse_dt(end_at)
    for h in db.hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and h["id"] == exclude_id:
            continue
        hs = calc.parse_dt(h["start_at"])
        he = calc.parse_dt(h["end_at"])
        if not _overlaps(s, e, hs, he):
            continue
        if h["courtroom"] == courtroom or h["judge_user_id"] == judge_user_id:
            raise errors.err(errors.ERR_HEARING_CONFLICT, "Hearing window conflicts")


@bp.post("/hearings")
def create_hearing():
    _, role = get_actor()
    require_role(role, {"Judge"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    motion_id = data.get("motion_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    motion = None
    if motion_id is not None:
        motion = domain.get_or_404(db.motions, motion_id)

    courtroom = validate.require_str(data, "courtroom")
    judge_user_id = validate.require_str(data, "judge_user_id")
    validate.require(data, "start_at", "end_at")
    start_at = data["start_at"]
    end_at = data["end_at"]
    s = calc.parse_dt(start_at)
    e = calc.parse_dt(end_at)
    if s is None or e is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid start_at/end_at")
    if not (e > s):
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_at must be after start_at")

    # Same-case referential integrity (priority 5).
    if motion is not None and motion["case_id"] != case_id:
        raise errors.err(errors.ERR_CROSS_CASE_REFERENCE, "motion belongs to a different case")

    _check_conflict(courtroom, judge_user_id, start_at, end_at)

    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "motion_id": motion_id,
        "courtroom": courtroom,
        "judge_user_id": judge_user_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
    })
    db.hearings[rec["id"]] = rec

    if motion is not None:
        motion["hearing_id"] = rec["id"]
        db.touch(motion)

    return success(domain._clean(rec), status=201)


@bp.get("/hearings/<hearing_id>")
def get_hearing(hearing_id):
    get_actor()
    rec = domain.get_or_404(db.hearings, hearing_id)
    return success(domain._clean(rec), status=200)


@bp.get("/hearings")
def list_hearings():
    get_actor()
    args = request.args
    items = list(db.hearings.values())
    for field in ("case_id", "motion_id", "courtroom", "judge_user_id", "status"):
        val = args.get(field)
        if val is not None:
            items = [h for h in items if h.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(h) for h in window], status=200, pagination=pagination)


@bp.post("/hearings/<hearing_id>/hold")
def hold_hearing(hearing_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    h = domain.get_or_404(db.hearings, hearing_id)
    if h["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Hearing is not SCHEDULED")
    clock = db.now_clock()
    if clock < calc.parse_dt(h["start_at"]):
        raise errors.err(errors.ERR_HEARING_NOT_STARTED, "Hearing has not started")
    h["status"] = "HELD"
    # Cascade: linked FILED motion -> UNDER_SUBMISSION.
    motion_id = h.get("motion_id")
    if motion_id:
        motion = db.motions.get(motion_id)
        if motion and motion["status"] == "FILED":
            motion["status"] = "UNDER_SUBMISSION"
            db.touch(motion)
    db.touch(h)
    return success(domain._clean(h), status=200)


@bp.post("/hearings/<hearing_id>/continue")
def continue_hearing(hearing_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    data = validate.body(request)
    h = domain.get_or_404(db.hearings, hearing_id)
    if h["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Hearing is not SCHEDULED")

    validate.require(data, "new_start_at", "new_end_at")
    new_start_at = data["new_start_at"]
    new_end_at = data["new_end_at"]
    s = calc.parse_dt(new_start_at)
    e = calc.parse_dt(new_end_at)
    if s is None or e is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid new_start_at/new_end_at")
    if not (e > s):
        raise errors.err(errors.ERR_INVALID_REQUEST, "new_end_at must be after new_start_at")

    _check_conflict(h["courtroom"], h["judge_user_id"], new_start_at, new_end_at, exclude_id=h["id"])

    successor = db.base_record()
    successor.update({
        "case_id": h["case_id"],
        "motion_id": h["motion_id"],
        "courtroom": h["courtroom"],
        "judge_user_id": h["judge_user_id"],
        "start_at": new_start_at,
        "end_at": new_end_at,
        "status": "SCHEDULED",
    })
    db.hearings[successor["id"]] = successor

    # Carry the motion link to the new hearing.
    if h.get("motion_id"):
        motion = db.motions.get(h["motion_id"])
        if motion:
            motion["hearing_id"] = successor["id"]
            db.touch(motion)

    h["status"] = "CONTINUED"
    db.touch(h)
    return success(domain._clean(h), status=200)


@bp.post("/hearings/<hearing_id>/cancel")
def cancel_hearing(hearing_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    h = domain.get_or_404(db.hearings, hearing_id)
    if h["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Hearing is not SCHEDULED")
    h["status"] = "CANCELLED"
    db.touch(h)
    return success(domain._clean(h), status=200)
