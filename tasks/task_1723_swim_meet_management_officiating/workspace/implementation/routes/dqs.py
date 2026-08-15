"""Disqualification endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import CLOCK, STORE, new_id
from errors import (
    ERR_DISQUALIFICATION_NOT_FOUND,
    ERR_DQ_ALREADY_ACTIVE,
    ERR_DQ_INVALID_STATE,
    ERR_EVENT_NOT_IN_PROGRESS,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_LANE_ASSIGNMENT_NOT_FOUND,
    ERR_LANE_NOT_RECONCILED,
    ERR_PROTEST_WINDOW_EXPIRED,
    ERR_PROTEST_WINDOW_OPEN,
    ERR_SEGREGATION_OF_DUTY,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    DQ_CODES,
    NON_TERMINAL_DQ_STATUSES,
    bump,
    cascade_dq_confirmed,
    cascade_dq_overturned,
    entry_team_id,
    get_or_404,
    paginate,
    pub_dq,
    req_body,
    sort_created,
    stamp,
    v_enum,
    v_str,
)

bp = Blueprint("dqs", __name__)


def _dq_context(dq):
    lane = STORE["lane_assignments"][dq["lane_assignment_id"]]
    event = STORE["events"][lane["event_id"]]
    meet = STORE["meets"][event["meet_id"]]
    return lane, event, meet


@bp.post("/lane-assignments/<lid>/disqualifications")
def record_dq(lid):
    user_id, role = ctx()
    require_role(role, "DeckOfficial")
    lane = get_or_404("lane_assignments", lid, ERR_LANE_ASSIGNMENT_NOT_FOUND)
    b = req_body()
    dq_code = v_enum(b, "dq_code", DQ_CODES)
    call_notes = v_str(b, "call_notes")
    event = STORE["events"][lane["event_id"]]
    # The caller must be an Official of this meet holding a CONFIRMED
    # STROKE_TURN_JUDGE assignment on this event.
    official = STORE["officials"].get(user_id)
    permitted = (
        official is not None
        and official["meet_id"] == event["meet_id"]
        and any(
            a["official_id"] == user_id
            and a["event_id"] == event["id"]
            and a["role_on_deck"] == "STROKE_TURN_JUDGE"
            and a["status"] == "CONFIRMED"
            for a in STORE["official_assignments"].values()
        )
    )
    if not permitted:
        raise_err(
            ERR_INSUFFICIENT_PERMISSIONS,
            "caller lacks a CONFIRMED STROKE_TURN_JUDGE assignment on this event",
        )
    if lane["reconciliation_status"] not in ("AUTO_CONFIRMED", "RESOLVED"):
        raise_err(ERR_LANE_NOT_RECONCILED, "lane is not reconciled")
    if event["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "event is not IN_PROGRESS or COMPLETED")
    for d in STORE["disqualifications"].values():
        if (
            d["lane_assignment_id"] == lane["id"]
            and d["status"] in NON_TERMINAL_DQ_STATUSES
        ):
            raise_err(ERR_DQ_ALREADY_ACTIVE, "a non-terminal DQ already exists on this lane")
    dq = stamp(
        {
            "id": new_id(),
            "lane_assignment_id": lane["id"],
            "reporting_official_id": user_id,
            "resolved_by_referee_id": None,
            "dq_code": dq_code,
            "call_notes": call_notes,
            "status": "RECORDED",
            "notified_at": None,
        }
    )
    STORE["disqualifications"][dq["id"]] = dq
    return ok_object(pub_dq(dq), 201)


@bp.get("/disqualifications/<did>")
def get_dq(did):
    ctx()
    dq = get_or_404("disqualifications", did, ERR_DISQUALIFICATION_NOT_FOUND)
    return ok_object(pub_dq(dq))


@bp.get("/disqualifications")
def list_dqs():
    ctx()
    items = list(STORE["disqualifications"].values())
    reporting = request.args.get("reporting_official_id")
    resolved = request.args.get("resolved_by_referee_id")
    if reporting is not None:
        items = [d for d in items if d["reporting_official_id"] == reporting]
    if resolved is not None:
        items = [d for d in items if d["resolved_by_referee_id"] == resolved]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_dq(d) for d in page], limit, offset, total)


@bp.post("/disqualifications/<did>/notify-coach")
def notify_coach(did):
    _, role = ctx()
    require_role(role, "MeetReferee")
    dq = get_or_404("disqualifications", did, ERR_DISQUALIFICATION_NOT_FOUND)
    if dq["status"] != "RECORDED":
        raise_err(ERR_DQ_INVALID_STATE, "notify-coach requires status RECORDED")
    dq["status"] = "COACH_NOTIFIED"
    dq["notified_at"] = CLOCK["now"]
    bump(dq)
    return ok_object(pub_dq(dq))


@bp.post("/disqualifications/<did>/protest")
def protest_dq(did):
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    dq = get_or_404("disqualifications", did, ERR_DISQUALIFICATION_NOT_FOUND)
    lane, event, meet = _dq_context(dq)
    entry = STORE["entries"].get(lane["entry_id"])
    # Ownership: the protested disqualification's team must match the coach.
    if entry is None or entry_team_id(entry) != user_id:
        raise_err(
            ERR_INSUFFICIENT_PERMISSIONS, "coach may only protest their own team's calls"
        )
    if dq["status"] != "COACH_NOTIFIED":
        raise_err(ERR_DQ_INVALID_STATE, "protest requires status COACH_NOTIFIED")
    window_end = dq["notified_at"] + timedelta(minutes=meet["dq_protest_window_minutes"])
    if CLOCK["now"] > window_end:  # equality allowed
        raise_err(ERR_PROTEST_WINDOW_EXPIRED, "the protest window has expired")
    dq["status"] = "PROTESTED"
    bump(dq)
    return ok_object(pub_dq(dq))


@bp.post("/disqualifications/<did>/confirm")
def confirm_dq(did):
    user_id, role = ctx()
    require_role(role, "MeetReferee")
    dq = get_or_404("disqualifications", did, ERR_DISQUALIFICATION_NOT_FOUND)
    # Segregation of duties: the ruling referee must differ from the reporter.
    if user_id == dq["reporting_official_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTY, "the reporting official may not rule on this DQ")
    if dq["status"] not in ("COACH_NOTIFIED", "UPHELD"):
        raise_err(ERR_DQ_INVALID_STATE, "confirm requires status COACH_NOTIFIED or UPHELD")
    if dq["status"] == "COACH_NOTIFIED":
        _, _, meet = _dq_context(dq)
        window_end = dq["notified_at"] + timedelta(
            minutes=meet["dq_protest_window_minutes"]
        )
        if not CLOCK["now"] > window_end:  # must be strictly past the window
            raise_err(ERR_PROTEST_WINDOW_OPEN, "the protest window is still open")
    dq["status"] = "CONFIRMED"
    dq["resolved_by_referee_id"] = user_id
    bump(dq)
    cascade_dq_confirmed(dq)
    return ok_object(pub_dq(dq))


@bp.post("/disqualifications/<did>/uphold")
def uphold_dq(did):
    user_id, role = ctx()
    require_role(role, "MeetReferee")
    dq = get_or_404("disqualifications", did, ERR_DISQUALIFICATION_NOT_FOUND)
    if user_id == dq["reporting_official_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTY, "the reporting official may not rule on this DQ")
    if dq["status"] != "PROTESTED":
        raise_err(ERR_DQ_INVALID_STATE, "uphold requires status PROTESTED")
    dq["status"] = "UPHELD"
    dq["resolved_by_referee_id"] = user_id
    bump(dq)
    return ok_object(pub_dq(dq))


@bp.post("/disqualifications/<did>/overturn")
def overturn_dq(did):
    user_id, role = ctx()
    require_role(role, "MeetReferee")
    dq = get_or_404("disqualifications", did, ERR_DISQUALIFICATION_NOT_FOUND)
    if user_id == dq["reporting_official_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTY, "the reporting official may not rule on this DQ")
    if dq["status"] != "PROTESTED":
        raise_err(ERR_DQ_INVALID_STATE, "overturn requires status PROTESTED")
    dq["status"] = "OVERTURNED"
    dq["resolved_by_referee_id"] = user_id
    bump(dq)
    cascade_dq_overturned(dq)
    return ok_object(pub_dq(dq))
