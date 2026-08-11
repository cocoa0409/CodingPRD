"""BoardMeeting routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import fmt_ts
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    get_captive,
    get_meeting,
    opt_str,
    parse_dt_field,
    req_enum,
    req_int,
    stamp_new,
    touch,
)

bp = Blueprint("meetings", __name__)

READ_ROLES = ("CaptiveManager", "BoardDirector")


def _agenda(data):
    items = data.get("agenda_items")
    if items is None:
        return []
    if not isinstance(items, list):
        raise ApiError("ERR_INVALID_REQUEST", "agenda_items must be an array")
    return items


@bp.post("/api/captives/<captiveId>/board-meetings")
def create_meeting(captiveId):
    user_id, role = require_roles("BoardDirector")
    get_captive(captiveId)
    data = body()
    meeting_date = parse_dt_field(data, "meeting_date")
    mtype = req_enum(data, "meeting_type", C.MEETING_TYPES)
    directors = req_int(data, "directors_present")
    agenda = _agenda(data)

    quorum_required = C.QUORUM_REQUIRED
    meeting = stamp_new()
    meeting.update({
        "captive_id": captiveId,
        "meeting_date": fmt_ts(meeting_date),
        "meeting_type": mtype,
        "quorum_required": quorum_required,
        "directors_present": directors,
        "quorum_met": directors >= quorum_required,
        "agenda_items": agenda,
        "resolutions_passed": [],
        "minutes_document_url": data.get("minutes_document_url"),
        "annual_meeting_completed": False,
        "status": "SCHEDULED",
    })
    db.meetings[meeting["id"]] = meeting
    log(captiveId, "GOVERNANCE_ACTION", "BoardMeeting", meeting["id"], role,
        user_id, "Board meeting scheduled", None, "SCHEDULED")
    return ok(meeting, 201)


@bp.get("/api/captives/<captiveId>/board-meetings")
def list_meetings(captiveId):
    require_roles(*READ_ROLES)
    get_captive(captiveId)
    items = [m for m in db.meetings.values() if m["captive_id"] == captiveId]
    mtype = request.args.get("meeting_type")
    if mtype:
        items = [m for m in items if m["meeting_type"] == mtype]
    status = request.args.get("status")
    if status:
        items = [m for m in items if m["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/board-meetings/<meetingId>")
def get_meeting_route(captiveId, meetingId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    return ok(get_meeting(captive, meetingId), 200)


@bp.post("/api/captives/<captiveId>/board-meetings/<meetingId>/convene")
def convene_meeting(captiveId, meetingId):
    user_id, role = require_roles("BoardDirector")
    captive = get_captive(captiveId)
    meeting = get_meeting(captive, meetingId)
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_MEETING_NOT_SCHEDULED",
                       "Board meeting must be in SCHEDULED state")
    if not meeting.get("quorum_met"):
        raise ApiError("ERR_QUORUM_NOT_MET", "Board meeting quorum not met")
    prev = meeting["status"]
    meeting["status"] = "IN_SESSION"
    touch(meeting)
    log(captiveId, "GOVERNANCE_ACTION", "BoardMeeting", meetingId, role,
        user_id, "Board meeting convened", prev, "IN_SESSION")
    return ok(meeting, 200)


@bp.post("/api/captives/<captiveId>/board-meetings/<meetingId>/draft-minutes")
def draft_minutes(captiveId, meetingId):
    user_id, role = require_roles("BoardDirector")
    captive = get_captive(captiveId)
    meeting = get_meeting(captive, meetingId)
    if meeting["status"] != "IN_SESSION":
        raise ApiError("ERR_MEETING_NOT_IN_SESSION",
                       "Board meeting must be in IN_SESSION state")
    data = body()
    prev = meeting["status"]
    meeting["status"] = "MINUTES_DRAFTED"
    resolutions = data.get("resolutions_passed")
    if resolutions is None:
        # Populate from the agenda: one resolution per agenda item.
        resolutions = [
            {
                "item_number": item.get("item_number"),
                "resolution_text": item.get("description"),
                "vote_result": "PASSED",
            }
            for item in meeting.get("agenda_items", [])
            if isinstance(item, dict)
        ]
    if not isinstance(resolutions, list):
        raise ApiError("ERR_INVALID_REQUEST", "resolutions_passed must be an array")
    meeting["resolutions_passed"] = resolutions
    url = data.get("minutes_document_url")
    if url is not None:
        meeting["minutes_document_url"] = url
    meeting["minutes_drafted_by"] = user_id
    touch(meeting)
    log(captiveId, "GOVERNANCE_ACTION", "BoardMeeting", meetingId, role,
        user_id, "Minutes drafted", prev, "MINUTES_DRAFTED")
    return ok(meeting, 200)


@bp.post("/api/captives/<captiveId>/board-meetings/<meetingId>/approve-minutes")
def approve_minutes(captiveId, meetingId):
    user_id, role = require_roles("BoardDirector")
    captive = get_captive(captiveId)
    meeting = get_meeting(captive, meetingId)
    if meeting["status"] != "MINUTES_DRAFTED":
        raise ApiError("ERR_MINUTES_NOT_DRAFTED",
                       "Board meeting minutes must be in MINUTES_DRAFTED state")
    if meeting.get("minutes_drafted_by") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Same user cannot perform both drafting and approval of the minutes")
    prev = meeting["status"]
    meeting["status"] = "MINUTES_APPROVED"
    if meeting.get("meeting_type") == "ANNUAL":
        meeting["annual_meeting_completed"] = True
    touch(meeting)
    log(captiveId, "GOVERNANCE_ACTION", "BoardMeeting", meetingId, role,
        user_id, "Minutes approved", prev, "MINUTES_APPROVED")
    return ok(meeting, 200)


@bp.post("/api/captives/<captiveId>/board-meetings/<meetingId>/file")
def file_meeting(captiveId, meetingId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    meeting = get_meeting(captive, meetingId)
    if meeting["status"] != "MINUTES_APPROVED":
        raise ApiError("ERR_MINUTES_NOT_APPROVED",
                       "Board meeting minutes must be in MINUTES_APPROVED state")
    prev = meeting["status"]
    meeting["status"] = "FILED"
    touch(meeting)
    log(captiveId, "GOVERNANCE_ACTION", "BoardMeeting", meetingId, role,
        user_id, "Meeting minutes filed", prev, "FILED")
    return ok(meeting, 200)


@bp.post("/api/captives/<captiveId>/board-meetings/<meetingId>/cancel")
def cancel_meeting(captiveId, meetingId):
    user_id, role = require_roles("BoardDirector")
    captive = get_captive(captiveId)
    meeting = get_meeting(captive, meetingId)
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_MEETING_NOT_SCHEDULED",
                       "Board meeting must be in SCHEDULED state")
    prev = meeting["status"]
    meeting["status"] = "CANCELLED"
    touch(meeting)
    log(captiveId, "GOVERNANCE_ACTION", "BoardMeeting", meetingId, role,
        user_id, "Board meeting cancelled", prev, "CANCELLED")
    return ok(meeting, 200)
