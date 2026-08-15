"""Drill and drill-message endpoints (PRD §3.5), including the RELAYED
self-loop and the delivered-only-after-relay rule."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_DRILL_NOT_IN_PROGRESS, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_MEMBERSHIP_NOT_ACTIVE, ERR_MESSAGE_NOT_RELAYED, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    PRECEDENCES, as_dt, as_enum, as_int, as_str, bad_request, body_json, need,
    opt, reject_unknown_fields,
)

bp = Blueprint("drills", __name__)

DRILL_STATUSES = {"PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
MESSAGE_STATUSES = {"ORIGINATED", "RELAYED", "DELIVERED", "CANCELLED"}
EC = {"EmergencyCoordinator"}
READ_ROLES = {"ClubAdmin", "EmergencyCoordinator", "Member"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


@bp.post("/drills")
def create_drill():
    _auth(EC)
    body = body_json(request)
    reject_unknown_fields(body, {"title", "scheduled_start", "scheduled_end",
                                 "passing_score"})
    title = as_str(need(body, "title"), "title")
    scheduled_start = as_dt(need(body, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(need(body, "scheduled_end"), "scheduled_end")
    passing_score = as_int(opt(body, "passing_score", 70), "passing_score")
    if passing_score < 0 or passing_score > 100:
        bad_request("passing_score must be in 0..100")
    drill = {
        "title": title,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "passing_score": passing_score,
        "status": "PLANNED",
    }
    svc.stamp_new(drill)
    db.STORE["drills"][drill["id"]] = drill
    return success(svc.ser_drill(drill), "object", 201)


@bp.get("/drills")
def list_drills():
    _auth(READ_ROLES)
    status = request.args.get("status")
    items = [svc.ser_drill(d) for d in svc.sorted_records("drills")
             if status is None or d["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/drills/<did>")
def get_drill(did):
    _auth(READ_ROLES)
    return success(svc.ser_drill(svc.get_drill(did)), "object", 200)


@bp.post("/drills/<did>/set-status")
def set_drill_status(did):
    _auth(EC)
    drill = svc.get_drill(did)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", DRILL_STATUSES)
    current = drill["status"]
    if to == "IN_PROGRESS":
        if current != "PLANNED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot start a drill in status %s" % current)
        if db.now() < drill["scheduled_start"]:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "drill may be started only at or after scheduled_start")
        drill["status"] = "IN_PROGRESS"
        svc.touch(drill)
    elif to == "COMPLETED":
        if current != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot complete a drill in status %s" % current)
        drill["status"] = "COMPLETED"
        svc.touch(drill)
    elif to == "CANCELLED":
        if current not in ("PLANNED", "IN_PROGRESS"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot cancel a drill in status %s" % current)
        drill["status"] = "CANCELLED"
        svc.touch(drill)
    else:  # PLANNED is never a manual target
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move a drill from %s to %s" % (current, to))
    return success(svc.ser_drill(drill), "object", 200)


# ---------------------------------------------------------------------------
# Drill messages
# ---------------------------------------------------------------------------

@bp.post("/drill-messages")
def create_message():
    user_id, role = _auth({"Member"})
    body = body_json(request)
    reject_unknown_fields(body, {"drill_id", "precedence"})
    drill_id = as_str(need(body, "drill_id"), "drill_id")
    drill = svc.get_drill(drill_id)  # body FK existence
    precedence = as_enum(need(body, "precedence"), "precedence", PRECEDENCES)
    member = svc.get_member(user_id)
    if drill["status"] != "IN_PROGRESS":
        raise ApiError(ERR_DRILL_NOT_IN_PROGRESS, 409,
                       "drill is not IN_PROGRESS")
    if member["membership_status"] != "ACTIVE":
        raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                       "membership_status is not ACTIVE")
    msg = {
        "drill_id": drill["id"],
        "originator_member_id": member["id"],
        "precedence": precedence,
        "relay_count": 0,
        "status": "ORIGINATED",
        "delivered_at": None,
        "handling_seconds": None,
    }
    svc.stamp_new(msg)
    db.STORE["drill_messages"][msg["id"]] = msg
    return success(svc.ser_message(msg), "object", 201)


@bp.get("/drill-messages")
def list_messages():
    _auth(READ_ROLES)
    drill_id = request.args.get("drill_id")
    originator = request.args.get("originator_member_id")
    status = request.args.get("status")
    items = []
    for m in svc.sorted_records("drill_messages"):
        if drill_id is not None and m["drill_id"] != drill_id:
            continue
        if originator is not None and m["originator_member_id"] != originator:
            continue
        if status is not None and m["status"] != status:
            continue
        items.append(svc.ser_message(m))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/drill-messages/<mid>")
def get_message(mid):
    _auth(READ_ROLES)
    return success(svc.ser_message(svc.get_message(mid)), "object", 200)


@bp.post("/drill-messages/<mid>/set-status")
def set_message_status(mid):
    user_id, role = _auth({"Member"})
    msg = svc.get_message(mid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", MESSAGE_STATUSES)
    drill = svc.get_drill(msg["drill_id"])
    member = svc.get_member(user_id)
    current = msg["status"]
    if to == "RELAYED":
        # ORIGINATED -> RELAYED and the RELAYED -> RELAYED self-loop both add a hop.
        if drill["status"] != "IN_PROGRESS":
            raise ApiError(ERR_DRILL_NOT_IN_PROGRESS, 409,
                           "drill is not IN_PROGRESS")
        if current not in ("ORIGINATED", "RELAYED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot relay a message in status %s" % current)
        if member["membership_status"] != "ACTIVE":
            raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                           "membership_status is not ACTIVE")
        msg["status"] = "RELAYED"
        msg["relay_count"] += 1
        svc.touch(msg)
    elif to == "DELIVERED":
        if drill["status"] != "IN_PROGRESS":
            raise ApiError(ERR_DRILL_NOT_IN_PROGRESS, 409,
                           "drill is not IN_PROGRESS")
        if current == "ORIGINATED":
            # A message that was never relayed cannot be delivered.
            raise ApiError(ERR_MESSAGE_NOT_RELAYED, 409,
                           "message has not passed through RELAYED")
        if current != "RELAYED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot deliver a message in status %s" % current)
        msg["status"] = "DELIVERED"
        msg["delivered_at"] = db.now()
        msg["handling_seconds"] = int(
            (msg["delivered_at"] - msg["created_at"]).total_seconds())
        svc.touch(msg)
    elif to == "CANCELLED":
        if current not in ("ORIGINATED", "RELAYED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot cancel a message in status %s" % current)
        # By the originator at any time, or by any member while the drill runs.
        if msg["originator_member_id"] != member["id"] \
                and drill["status"] != "IN_PROGRESS":
            raise ApiError(ERR_FORBIDDEN, 403,
                           "only the originator may cancel once the drill has moved on")
        msg["status"] = "CANCELLED"
        svc.touch(msg)
    else:  # ORIGINATED is never a manual target
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move a message from %s to %s" % (current, to))
    return success(svc.ser_message(msg), "object", 200)
