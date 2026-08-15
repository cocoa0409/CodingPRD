"""EscortAssignment offer, listing, accept/decline/release, check-ins."""

from flask import Blueprint, request

import db
from errors import (
    ERR_ESCORT_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_LEG_INVALID_STATE,
    ERR_JOB_INVALID_STATE,
    ERR_ASSIGNMENT_INVALID_STATE,
    ERR_ESCORT_INVALID_STATE,
    ERR_ESCORT_NOT_CERTIFIED_FOR_STATE,
    ERR_HEIGHT_POLE_EQUIPMENT_MISSING,
    ERR_ESCORT_WINDOW_CONFLICT,
    ERR_POSITION_QUOTA_FILLED,
    ERR_NO_ELIGIBLE_ESCORT,
    raise_err,
)
from middleware import require_roles, check_assignment_owner, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_assignment
from services import calc, cascade
from util import body_json, req_enum, new_id

bp = Blueprint("assignments", __name__)

NON_TERMINAL_ASSIGNMENT_STATES = ("OFFERED", "ACCEPTED", "ACTIVE")


def _get_assignment_or_404(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {assignment_id} not found")
    return a


def _position_fill_count(leg_id, position):
    return sum(
        1
        for a in db.assignments.values()
        if a["leg_id"] == leg_id
        and a["position"] == position
        and a["assignment_status"] in NON_TERMINAL_ASSIGNMENT_STATES
    )


def _check_position_quota(leg, position):
    required = (leg["required_front_escorts"] if position == "FRONT"
                else leg["required_rear_escorts"])
    if _position_fill_count(leg["id"], position) >= required:
        raise_err(ERR_POSITION_QUOTA_FILLED,
                  f"The leg already has its required number of {position} assignments")


@bp.post("/legs/<id>/assignments")
def offer_assignment(id):
    require_roles("Dispatcher")
    data = body_json(request)
    position = req_enum(data, "position", calc.POSITIONS)
    escort_id = data.get("escort_id")
    if escort_id is not None and not isinstance(escort_id, str):
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "escort_id must be a string")

    leg = db.legs.get(id)
    if leg is None:
        from errors import ERR_LEG_NOT_FOUND
        raise_err(ERR_LEG_NOT_FOUND, f"Leg {id} not found")
    job = cascade.job_of_leg(leg)

    if leg["leg_status"] not in ("DETERMINED", "CLEARED"):
        raise_err(ERR_LEG_INVALID_STATE,
                  "Assignments may only be offered on a DETERMINED or CLEARED leg")

    if escort_id is not None:
        escort = db.escorts.get(escort_id)
        if escort is None:
            raise_err(ERR_ESCORT_NOT_FOUND, f"Escort {escort_id} not found")
        if leg["state_code"] not in escort["certified_state_codes"]:
            raise_err(ERR_ESCORT_NOT_CERTIFIED_FOR_STATE,
                      "Escort is not certified for the leg's state")
        if position == "FRONT" and leg["requires_height_pole"]:
            if (not escort["has_height_pole"]
                    or escort["height_pole_max_inches"] < job["height_inches"]):
                raise_err(ERR_HEIGHT_POLE_EQUIPMENT_MISSING,
                          "Escort lacks a height pole reaching the job's height")
        if not cascade.escort_window_free(escort, job):
            raise_err(ERR_ESCORT_WINDOW_CONFLICT,
                      "The escort's buffered availability conflicts with this job window")
        _check_position_quota(leg, position)
    else:
        _check_position_quota(leg, position)
        escort = cascade.select_escort(leg, job, position)
        if escort is None:
            raise_err(ERR_NO_ELIGIBLE_ESCORT,
                      "No ACTIVE, certified, equipped, window-free escort is available")

    n = db.now()
    assignment = {
        "id": new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
        "leg_id": leg["id"],
        "escort_id": escort["id"],
        "position": position,
        "assignment_status": "OFFERED",
        "offered_at": n,
        "accepted_at": None,
        "activated_at": None,
        "completed_at": None,
        "released_at": None,
        "release_cause": None,
        "billable_hours": None,
        "assignment_fee_cents": None,
        "last_checkin_at": None,
    }
    db.assignments[assignment["id"]] = assignment
    return success_object(ser_assignment(assignment), status=201)


@bp.get("/legs/<id>/assignments")
def list_leg_assignments(id):
    require_roles(*ALL_ROLES)
    leg = db.legs.get(id)
    if leg is None:
        from errors import ERR_LEG_NOT_FOUND
        raise_err(ERR_LEG_NOT_FOUND, f"Leg {id} not found")
    rows = cascade.assignments_of_leg(leg["id"])
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return paginate(request, [ser_assignment(a) for a in rows])


@bp.get("/assignments/<id>")
def get_assignment(id):
    require_roles(*ALL_ROLES)
    return success_object(ser_assignment(_get_assignment_or_404(id)))


@bp.get("/assignments")
def list_assignments():
    require_roles(*ALL_ROLES)
    escort_id = request.args.get("escort_id")
    leg_id = request.args.get("leg_id")
    status = request.args.get("assignment_status")
    rows = list(db.assignments.values())
    if escort_id is not None:
        rows = [a for a in rows if a["escort_id"] == escort_id]
    if leg_id is not None:
        rows = [a for a in rows if a["leg_id"] == leg_id]
    if status is not None:
        rows = [a for a in rows if a["assignment_status"] == status]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return paginate(request, [ser_assignment(a) for a in rows])


@bp.post("/assignments/<id>/accept")
def accept_assignment(id):
    uid, _role = require_roles("EscortOperator")
    body_json(request)
    a = _get_assignment_or_404(id)
    check_assignment_owner(a)
    if a["assignment_status"] != "OFFERED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "Acceptance requires the assignment to be OFFERED")
    escort = db.escorts.get(a["escort_id"])
    if escort is None or escort["escort_status"] != "ACTIVE":
        raise_err(ERR_ESCORT_INVALID_STATE, "The escort must be ACTIVE to accept")
    job = cascade.job_of_assignment(a)
    if job is None or job["job_status"] not in ("BOOKED", "CLEARED", "SCHEDULED"):
        raise_err(ERR_JOB_INVALID_STATE,
                  "The leg's job must be BOOKED, CLEARED, or SCHEDULED to accept")
    if not cascade.escort_window_free(escort, job):
        raise_err(ERR_ESCORT_WINDOW_CONFLICT,
                  "The escort's buffered availability conflicts with this job window")
    a["assignment_status"] = "ACCEPTED"
    a["accepted_at"] = db.now()
    mark(a)
    return success_object(ser_assignment(a))


@bp.post("/assignments/<id>/decline")
def decline_assignment(id):
    uid, _role = require_roles("EscortOperator")
    body_json(request)
    a = _get_assignment_or_404(id)
    check_assignment_owner(a)
    if a["assignment_status"] != "OFFERED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "Declining requires the assignment to be OFFERED")
    a["assignment_status"] = "DECLINED"
    mark(a)
    return success_object(ser_assignment(a))


@bp.post("/assignments/<id>/release")
def release_assignment(id):
    require_roles("Dispatcher")
    body_json(request)
    a = _get_assignment_or_404(id)
    if a["assignment_status"] not in ("OFFERED", "ACCEPTED"):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "Release requires the assignment to be OFFERED or ACCEPTED")
    cascade.release_assignment(a, "DISPATCHER")
    return success_object(ser_assignment(a))


@bp.post("/assignments/<id>/check-ins")
def check_in(id):
    uid, _role = require_roles("EscortOperator")
    body_json(request)
    a = _get_assignment_or_404(id)
    check_assignment_owner(a)
    if a["assignment_status"] not in ("ACCEPTED", "ACTIVE"):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "Check-ins are allowed only while the assignment is ACCEPTED or ACTIVE")
    a["last_checkin_at"] = db.now()
    mark(a)
    return success_object(ser_assignment(a), status=201)
