"""LaneAssignment and timing endpoints."""

from flask import Blueprint, request

from db import STORE
from errors import (
    ERR_EVENT_NOT_IN_PROGRESS,
    ERR_INVALID_REQUEST,
    ERR_LANE_ASSIGNMENT_NOT_FOUND,
    ERR_LANE_NOT_RECONCILED,
    ERR_LANE_VOIDED,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    PAD_STATUSES,
    VARIANTS,
    auto_confirmable,
    bump,
    chain_time,
    get_or_404,
    is_int,
    meet_of_event,
    paginate,
    pub_dq,
    pub_lane,
    req_body,
    sort_created,
    v_enum,
    v_enum_opt,
)

bp = Blueprint("lanes", __name__)

READING_FIELDS = ("pad_cs", "backup1_cs", "backup2_cs", "watch_cs")


@bp.get("/lane-assignments/<lid>")
def get_lane(lid):
    ctx()
    lane = get_or_404("lane_assignments", lid, ERR_LANE_ASSIGNMENT_NOT_FOUND)
    return ok_object(pub_lane(lane))


@bp.get("/lane-assignments")
def list_lanes():
    ctx()
    items = list(STORE["lane_assignments"].values())
    event_id = request.args.get("event_id")
    entry_id = request.args.get("entry_id")
    if event_id is not None:
        items = [l for l in items if l["event_id"] == event_id]
    if entry_id is not None:
        items = [l for l in items if l["entry_id"] == entry_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_lane(l) for l in page], limit, offset, total)


@bp.post("/lane-assignments/<lid>/readings")
def submit_readings(lid):
    _, role = ctx()
    require_role(role, "TimingOperator")
    lane = get_or_404("lane_assignments", lid, ERR_LANE_ASSIGNMENT_NOT_FOUND)
    b = req_body()
    # Type sanity on supplied fields.
    supplied = {}
    for f in READING_FIELDS:
        if f in b and b[f] is not None:
            if not is_int(b[f]):
                raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % f)
            supplied[f] = b[f]
    pad_status = v_enum_opt(b, "pad_status", PAD_STATUSES, None) if b.get("pad_status") is not None else None
    if lane["lane_status"] != "ACTIVE":
        raise_err(ERR_LANE_VOIDED, "lane is VOIDED")
    event = STORE["events"][lane["event_id"]]
    if event["status"] != "IN_PROGRESS":
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "event is not IN_PROGRESS")
    # Payload sanity (last): at least one timing value must be present.
    if not supplied:
        raise_err(ERR_INVALID_REQUEST, "at least one timing reading is required")
    for f, v in supplied.items():
        lane[f] = v
    if pad_status is not None:
        lane["pad_status"] = pad_status
    meet = meet_of_event(event)
    if auto_confirmable(lane, meet):
        lane["reconciliation_status"] = "AUTO_CONFIRMED"
        lane["reconciled_variant"] = "PRIMARY_PRIORITY"
        lane["final_time_cs"] = lane["pad_cs"]
    else:
        lane["reconciliation_status"] = "MANUAL_REVIEW"
        lane["reconciled_variant"] = None
        lane["final_time_cs"] = None
    bump(lane)
    return ok_object(pub_lane(lane))


@bp.post("/lane-assignments/<lid>/resolve")
def resolve_lane(lid):
    _, role = ctx()
    require_role(role, "TimingOperator")
    lane = get_or_404("lane_assignments", lid, ERR_LANE_ASSIGNMENT_NOT_FOUND)
    b = req_body()
    variant = v_enum(b, "variant", VARIANTS)
    pad_status = v_enum_opt(b, "pad_status", PAD_STATUSES, None) if b.get("pad_status") is not None else None
    event = STORE["events"][lane["event_id"]]
    if event["status"] != "IN_PROGRESS":
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "event is not IN_PROGRESS")
    if lane["reconciliation_status"] != "MANUAL_REVIEW":
        raise_err(ERR_LANE_NOT_RECONCILED, "lane is not in MANUAL_REVIEW")
    if pad_status is not None:
        lane["pad_status"] = pad_status
    lane["reconciled_variant"] = variant
    lane["final_time_cs"] = chain_time(lane, variant)
    lane["reconciliation_status"] = "RESOLVED"
    bump(lane)
    return ok_object(pub_lane(lane))


@bp.post("/lane-assignments/<lid>/reopen-timing")
def reopen_timing(lid):
    _, role = ctx()
    require_role(role, "MeetReferee")
    lane = get_or_404("lane_assignments", lid, ERR_LANE_ASSIGNMENT_NOT_FOUND)
    event = STORE["events"][lane["event_id"]]
    if event["status"] != "IN_PROGRESS":
        raise_err(ERR_EVENT_NOT_IN_PROGRESS, "event is not IN_PROGRESS")
    if lane["reconciliation_status"] not in ("RESOLVED", "AUTO_CONFIRMED"):
        raise_err(ERR_LANE_NOT_RECONCILED, "lane timing is not settled")
    lane["reconciliation_status"] = "MANUAL_REVIEW"
    lane["final_time_cs"] = None
    lane["reconciled_variant"] = None
    bump(lane)
    return ok_object(pub_lane(lane))


@bp.get("/lane-assignments/<lid>/disqualifications")
def lane_dqs(lid):
    ctx()
    lane = get_or_404("lane_assignments", lid, ERR_LANE_ASSIGNMENT_NOT_FOUND)
    items = sort_created(
        [
            d
            for d in STORE["disqualifications"].values()
            if d["lane_assignment_id"] == lane["id"]
        ]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub_dq(d) for d in page], limit, offset, total)
