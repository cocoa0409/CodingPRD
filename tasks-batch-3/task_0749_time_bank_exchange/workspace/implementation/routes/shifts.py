"""ProjectShift GET routes + assignment sub-resource."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE,
                    ERR_MEMBER_SUSPENDED, ERR_SHIFT_TIME_CONFLICT)
from response import envelope_object, envelope_array
from services import validators, pagination, balance, projects
from services.serializers import project_shift_dto, shift_assignment_dto
from db import parse_iso

bp = Blueprint("shifts", __name__)


@bp.route("/shifts/<sid>", methods=["GET"])
def get_shift(sid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    s = db.project_shifts.get(sid)
    if s is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Shift not found")
    return envelope_object(project_shift_dto(s), status=200)


def _shift_windows_overlap(a_start_ts, a_dur_min, b_start_ts, b_dur_min):
    """Half-open [start, end) intervals. Touching endpoints = ALLOWED."""
    a_end = a_start_ts + a_dur_min * 60
    b_end = b_start_ts + b_dur_min * 60
    return a_start_ts < b_end and b_start_ts < a_end


@bp.route("/shifts/<sid>/assignments", methods=["POST"])
def create_assignment(sid):
    user_id, _ = require_role({ROLE_MEMBER})
    shift = db.project_shifts.get(sid)
    if shift is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Shift not found")
    project = db.group_projects.get(shift["project_id"])
    if project is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Project not found")

    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["member_id"])
    member_id = validators.require_str(payload, "member_id")

    m = db.members.get(member_id)
    if m is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")

    # priority 4 state
    if shift["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Shift.status must be OPEN")

    # priority 6 ownership
    if member_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal assignment.member_id")

    # priority 7 suspension
    balance.recompute_member_snapshot(member_id, bump_version=False)
    if m["is_suspended"]:
        raise_err(ERR_MEMBER_SUSPENDED, "member is suspended")

    # priority 9 temporal-overlap on ShiftAssignments
    shift_start_ts = parse_iso(shift["shift_start_utc"]).timestamp()
    shift_dur = shift["duration_minutes"]
    for a in db.shift_assignments.values():
        if a["member_id"] != member_id or a["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        other_shift = db.project_shifts.get(a["shift_id"])
        if other_shift is None:
            continue
        os_ts = parse_iso(other_shift["shift_start_utc"]).timestamp()
        if _shift_windows_overlap(shift_start_ts, shift_dur, os_ts, other_shift["duration_minutes"]):
            raise_err(ERR_SHIFT_TIME_CONFLICT, "overlapping active assignment for member")

    # Also enforce project must be in a state that accepts new assignments (published, not cancelled).
    projects.recompute_aggregate_state(project)
    if project["aggregate_state"] not in ("OPEN", "IN_PROGRESS"):
        raise_err(ERR_INVALID_STATE, "project must be OPEN or IN_PROGRESS to accept assignments")

    a = {
        "shift_id": sid,
        "member_id": member_id,
        "status": "CONFIRMED",
        "check_in_utc": None,
    }
    db.stamp_new(a)
    db.shift_assignments[a["id"]] = a

    # Check capacity: if confirmed count == capacity, transition shift OPEN -> FILLED
    confirmed = [x for x in db.shift_assignments.values()
                 if x["shift_id"] == sid and x["status"] == "CONFIRMED"]
    if len(confirmed) >= shift["capacity"]:
        shift["status"] = "FILLED"
        db.touch(shift)
    projects.recompute_total_committed_minutes(project["id"])
    projects.recompute_aggregate_state(project)
    return envelope_object(shift_assignment_dto(a), status=201)


@bp.route("/shifts/<sid>/assignments", methods=["GET"])
def list_shift_assignments(sid):
    require_role({ROLE_MEMBER, ROLE_ORGANIZER, ROLE_ADMIN})
    if db.project_shifts.get(sid) is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Shift not found")
    limit, offset = pagination.parse_pagination()
    items = [a for a in db.shift_assignments.values() if a["shift_id"] == sid]
    for k in ("status", "member_id"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([shift_assignment_dto(a) for a in window], limit, offset, total)


@bp.route("/shifts/<sid>/assignments/<aid>", methods=["DELETE"])
def cancel_assignment(sid, aid):
    user_id, _ = require_role({ROLE_MEMBER})
    shift = db.project_shifts.get(sid)
    if shift is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Shift not found")
    a = db.shift_assignments.get(aid)
    if a is None or a["shift_id"] != sid:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Assignment not found")
    if a["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Assignment.status must be CONFIRMED")
    if a["member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal assignment.member_id")
    if db.clock_dt() >= parse_iso(shift["shift_start_utc"]):
        raise_err(ERR_INVALID_STATE, "cannot cancel on or after shift_start_utc")
    a["status"] = "CANCELLED"
    db.touch(a)
    # FILLED -> OPEN if count drops
    if shift["status"] == "FILLED":
        confirmed = [x for x in db.shift_assignments.values()
                     if x["shift_id"] == sid and x["status"] == "CONFIRMED"]
        if len(confirmed) < shift["capacity"]:
            shift["status"] = "OPEN"
            db.touch(shift)
    projects.recompute_total_committed_minutes(shift["project_id"])
    proj = db.group_projects.get(shift["project_id"])
    if proj is not None:
        projects.recompute_aggregate_state(proj)
    return envelope_object(shift_assignment_dto(a), status=200)
