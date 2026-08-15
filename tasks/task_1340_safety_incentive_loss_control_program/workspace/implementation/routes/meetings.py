"""Committee meetings and their nested action items (PRD 3.5)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core, ops

bp = Blueprint("meetings", __name__)


@bp.route("/safety/committee-meetings", methods=["POST"])
def create_meeting():
    auth(["CommitteeChair", "EHSAdmin"])
    body = core.body_json()
    program_id = core.req_str(body, "program_id")
    scheduled_start = core.req_datetime(body, "scheduled_start")
    scheduled_end = core.req_datetime(body, "scheduled_end")
    location = core.req_str(body, "location")
    core.get_or_404("programs", program_id, "SafetyProgram")
    if not (scheduled_end > scheduled_start):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_end must be after scheduled_start")
    # Half-open interval overlap: [start, end) conflicts iff
    # start < existing.end AND end > existing.start; adjacency is allowed.
    for m in db.DB["meetings"].values():
        if m["program_id"] != program_id or m["status"] not in ("SCHEDULED", "HELD"):
            continue
        if scheduled_start < m["scheduled_end"] and scheduled_end > m["scheduled_start"]:
            raise ApiError("ERR_MEETING_OVERLAP", 409,
                           "The meeting interval overlaps another SCHEDULED|HELD meeting")
    m = core.stamp_new({
        "id": core.new_id(),
        "program_id": program_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "location": location,
        "attendee_ids": [],
        "minutes_text": None,
        "open_action_count": 0,
        "status": "SCHEDULED",
    })
    db.DB["meetings"][m["id"]] = m
    return ok(core.meeting_view(m), 201)


@bp.route("/safety/committee-meetings", methods=["GET"])
def list_meetings():
    auth(ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.DB["meetings"].values())
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.meeting_view(m) for m in page], total, limit, offset)


@bp.route("/safety/committee-meetings/<mid>", methods=["GET"])
def get_meeting(mid):
    auth(ALL_ROLES)
    m = core.get_or_404("meetings", mid, "CommitteeMeeting")
    return ok(core.meeting_view(m))


@bp.route("/safety/committee-meetings/<mid>/hold", methods=["POST"])
def hold_meeting(mid):
    auth(["CommitteeChair"])
    m = core.get_or_404("meetings", mid, "CommitteeMeeting")
    body = core.body_json()
    attendee_ids = core.req_list(body, "attendee_ids")
    attendees = []
    for aid in attendee_ids:
        if not isinstance(aid, str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "attendee_ids must be an array of employee ids")
        attendees.append(core.get_or_404("employees", aid, "Employee"))
    if m["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED meeting can be held")
    program = core.get_or_404("programs", m["program_id"], "SafetyProgram")
    distinct_committee = {a["id"] for a in attendees if a["committee_member"]}
    if len(distinct_committee) < program["quorum_min"]:
        raise ApiError("ERR_QUORUM_NOT_MET", 422,
                       "Distinct committee-member attendance below quorum_min")
    m["attendee_ids"] = list(attendee_ids)
    m["status"] = "HELD"
    core.touch(m)
    # Each distinct committee-member attendee earns MEETING_ATTENDED points.
    for emp_id in sorted(distinct_committee,
                         key=lambda eid: db.DB["employees"][eid]["_seq"]):
        ops.create_event(m["program_id"], emp_id, "MEETING_ATTENDED", m["id"])
    return ok(core.meeting_view(m))


@bp.route("/safety/committee-meetings/<mid>/publish-minutes", methods=["POST"])
def publish_minutes(mid):
    auth(["CommitteeChair"])
    m = core.get_or_404("meetings", mid, "CommitteeMeeting")
    body = core.body_json()
    minutes_text = core.req_str(body, "minutes_text")
    if m["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a HELD meeting can publish minutes")
    m["minutes_text"] = minutes_text
    m["status"] = "MINUTES_PUBLISHED"
    core.touch(m)
    return ok(core.meeting_view(m))


@bp.route("/safety/committee-meetings/<mid>/cancel", methods=["POST"])
def cancel_meeting(mid):
    auth(["CommitteeChair"])
    m = core.get_or_404("meetings", mid, "CommitteeMeeting")
    core.body_json()
    if m["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SCHEDULED meeting can be cancelled")
    m["status"] = "CANCELLED"
    core.touch(m)
    return ok(core.meeting_view(m))


@bp.route("/safety/committee-meetings/<mid>/action-items", methods=["POST"])
def create_action_item(mid):
    auth(["CommitteeChair"])
    m = core.get_or_404("meetings", mid, "CommitteeMeeting")
    body = core.body_json()
    assignee_id = core.req_str(body, "assignee_id")
    description = core.req_str(body, "description")
    due_date = core.req_datetime(body, "due_date")
    hazard_id = core.opt_str(body, "hazard_id", default=None)
    core.get_or_404("employees", assignee_id, "Employee")
    if hazard_id is not None:
        core.get_or_404("hazards", hazard_id, "Hazard")
    if m["status"] not in ("HELD", "MINUTES_PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Action items can be created only in a HELD or "
                       "MINUTES_PUBLISHED meeting")
    a = core.stamp_new({
        "id": core.new_id(),
        "meeting_id": m["id"],
        "assignee_id": assignee_id,
        "description": description,
        "due_date": due_date,
        "hazard_id": hazard_id,
        "completed_at": None,
        "verified_by": None,
        "status": "ASSIGNED",
    })
    db.DB["action_items"][a["id"]] = a
    m["open_action_count"] += 1
    core.touch(m)
    return ok(core.action_item_view(a), 201)


@bp.route("/safety/committee-meetings/<mid>/action-items", methods=["GET"])
def list_meeting_action_items(mid):
    auth(ALL_ROLES)
    m = core.get_or_404("meetings", mid, "CommitteeMeeting")
    status = request.args.get("status")
    items = [a for a in db.DB["action_items"].values() if a["meeting_id"] == m["id"]]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.action_item_view(a) for a in page], total, limit, offset)
