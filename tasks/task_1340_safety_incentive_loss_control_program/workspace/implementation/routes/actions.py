"""Action items: global reads, complete, verify, reassign (PRD 3.5)."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core, ops

bp = Blueprint("action_items", __name__)


@bp.route("/safety/action-items", methods=["GET"])
def list_action_items():
    auth(ALL_ROLES)
    meeting_id = request.args.get("meeting_id")
    assignee_id = request.args.get("assignee_id")
    status = request.args.get("status")
    hazard_id = request.args.get("hazard_id")
    items = list(db.DB["action_items"].values())
    if meeting_id is not None:
        items = [a for a in items if a["meeting_id"] == meeting_id]
    if assignee_id is not None:
        items = [a for a in items if a["assignee_id"] == assignee_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if hazard_id is not None:
        items = [a for a in items if a["hazard_id"] == hazard_id]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.action_item_view(a) for a in page], total, limit, offset)


@bp.route("/safety/action-items/<aid>", methods=["GET"])
def get_action_item(aid):
    auth(ALL_ROLES)
    a = core.get_or_404("action_items", aid, "ActionItem")
    return ok(core.action_item_view(a))


@bp.route("/safety/action-items/<aid>/complete", methods=["POST"])
def complete_action_item(aid):
    user_id, role = auth(["Supervisor", "SafetyManager", "CommitteeChair"])
    a = core.get_or_404("action_items", aid, "ActionItem")
    body = core.body_json()
    completed_at = core.opt_datetime(body, "completed_at", default=None)
    # Ownership: the assignee themself, or any CommitteeChair.
    if role != "CommitteeChair" and user_id != a["assignee_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the assignee or a CommitteeChair can complete this item")
    if a["status"] not in ("ASSIGNED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ASSIGNED or ESCALATED item can be completed")
    if completed_at is None:
        completed_at = CLOCK.now()
    if completed_at > CLOCK.now():
        raise ApiError("ERR_FUTURE_DATE_NOT_ALLOWED", 422,
                       "completed_at must not be in the future")
    a["status"] = "COMPLETED"
    a["completed_at"] = completed_at
    core.touch(a)
    return ok(core.action_item_view(a))


@bp.route("/safety/action-items/<aid>/verify", methods=["POST"])
def verify_action_item(aid):
    user_id, _ = auth(["CommitteeChair"])
    a = core.get_or_404("action_items", aid, "ActionItem")
    body = core.body_json()
    outcome = core.req_enum(body, "outcome", ("PASS", "FAIL"))
    outcome_note = core.opt_str(body, "outcome_note", default=None)
    new_due = core.opt_datetime(body, "due_date", default=None)
    if outcome == "FAIL" and (outcome_note is None or new_due is None):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "A FAIL outcome requires outcome_note and a new due_date")
    if a["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a COMPLETED item can be verified")
    if user_id == a["assignee_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "The verifier must differ from the assignee")
    m = core.get_or_404("meetings", a["meeting_id"], "CommitteeMeeting")
    if outcome == "PASS":
        a["status"] = "VERIFIED"
        a["verified_by"] = user_id
        core.touch(a)
        ops.create_event(m["program_id"], a["assignee_id"],
                         "ACTION_VERIFIED", a["id"])
        m["open_action_count"] -= 1
        core.touch(m)
    else:
        a["status"] = "ASSIGNED"
        a["due_date"] = new_due
        a["completed_at"] = None
        core.touch(a)
        # The item returns to ASSIGNED, which still counts as open: the
        # meeting's open_action_count is untouched by failure.
    return ok(core.action_item_view(a))


@bp.route("/safety/action-items/<aid>/reassign", methods=["POST"])
def reassign_action_item(aid):
    auth(["CommitteeChair"])
    a = core.get_or_404("action_items", aid, "ActionItem")
    body = core.body_json()
    due_date = core.req_datetime(body, "due_date")
    assignee_id = core.opt_str(body, "assignee_id", default=None)
    meeting_id = core.opt_str(body, "meeting_id", default=None)
    if assignee_id is not None:
        core.get_or_404("employees", assignee_id, "Employee")
    new_meeting = None
    if meeting_id is not None:
        new_meeting = core.get_or_404("meetings", meeting_id, "CommitteeMeeting")
    if a["status"] != "ESCALATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ESCALATED item can be reassigned")
    old_meeting = core.get_or_404("meetings", a["meeting_id"], "CommitteeMeeting")
    if new_meeting is not None:
        if new_meeting["program_id"] != old_meeting["program_id"] \
                or new_meeting["status"] not in ("HELD", "MINUTES_PUBLISHED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "meeting_id must name a HELD|MINUTES_PUBLISHED meeting "
                           "of the same program")
    a["status"] = "ASSIGNED"
    a["due_date"] = due_date
    if assignee_id is not None:
        a["assignee_id"] = assignee_id
    if new_meeting is not None and new_meeting["id"] != old_meeting["id"]:
        # Carry-over conserves the global open count: decrement the source,
        # increment the target.
        a["meeting_id"] = new_meeting["id"]
        old_meeting["open_action_count"] -= 1
        core.touch(old_meeting)
        new_meeting["open_action_count"] += 1
        core.touch(new_meeting)
    core.touch(a)
    return ok(core.action_item_view(a))
