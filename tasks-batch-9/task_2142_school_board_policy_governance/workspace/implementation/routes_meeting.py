"""Meetings: scheduling, notice, opening, adjournment and the minutes axis."""

from flask import Blueprint

import auth
import calc
import resp
import store
import validate as v
from errors import fail
from store import db, set_fields, touch

bp = Blueprint("meeting", __name__)

SCOPES = ["FULL_BOARD", "COMMITTEE"]
MEETING_TYPES = ["REGULAR", "SPECIAL", "EMERGENCY"]
COMMENT_RULES = ["FIRST_COME_CAPPED", "EQUAL_SPLIT"]
MEETING_STATUSES = ["DRAFT", "NOTICED", "OPEN", "ADJOURNED"]
MINUTES_STATUSES = ["NOT_DRAFTED", "DRAFTED", "APPROVED"]


@bp.post("/governance/meetings")
def create_meeting():
    auth.authorize(["BoardClerk"])
    body = v.body()
    title = v.req_str(body, "title")
    scope = v.req_enum(body, "scope", SCOPES)
    meeting_type = v.req_enum(body, "meeting_type", MEETING_TYPES)
    scheduled = v.req_dt(body, "scheduled_start_utc")
    committee_id = v.opt_id(body, "committee_id")
    rule = v.opt_enum(body, "public_comment_rule", COMMENT_RULES,
                      "FIRST_COME_CAPPED")

    if scope == "COMMITTEE" and committee_id is None:
        fail("ERR_INVALID_REQUEST",
             "committee_id is required when scope is COMMITTEE.")
    if scope == "FULL_BOARD" and committee_id is not None:
        fail("ERR_INVALID_REQUEST",
             "committee_id must be omitted when scope is FULL_BOARD.")

    if committee_id is not None:
        v.find("committees", committee_id)

    for other in db["meetings"].values():
        if other["status"] not in ("DRAFT", "NOTICED", "OPEN"):
            continue
        if other["scope"] != scope or other.get("committee_id") != committee_id:
            continue
        delta = abs((other["scheduled_start_utc"] - scheduled).total_seconds())
        if delta < calc.MEETING_SEPARATION_MINUTES * 60:
            fail("ERR_MEETING_SEPARATION_VIOLATION",
                 "Another live meeting starts within the separation buffer.")

    budget = calc.PUBLIC_COMMENT_BUDGET_MINUTES[meeting_type]
    rec = store.create("meetings", "Meeting", {
        "title": title,
        "scope": scope,
        "committee_id": committee_id,
        "meeting_type": meeting_type,
        "scheduled_start_utc": scheduled,
        "public_comment_rule": rule,
        "status": "DRAFT",
        "minutes_status": "NOT_DRAFTED",
        "minutes_approved_at_meeting_id": None,
        "notice_posted_at": None,
        "agenda_locked_at": None,
        "opened_at": None,
        "adjourned_at": None,
        "seated_member_count_snapshot": 0,
        "attending_member_ids": [],
        "quorum_required": 0,
        "public_comment_minutes_budget": budget,
        "public_comment_minutes_remaining": budget,
        "public_comment_allocation_variant": None,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/meetings")
def list_meetings():
    auth.authorize(auth.READ_ROLES_PUBLIC)
    limit, offset = v.pagination()
    committee_id = v.query_str("committee_id")
    status = v.query_enum("status", MEETING_STATUSES)
    minutes_status = v.query_enum("minutes_status", MINUTES_STATUSES)
    approved_at = v.query_str("minutes_approved_at_meeting_id")
    items = store.sorted_rows("meetings")
    if committee_id is not None:
        items = [m for m in items if m.get("committee_id") == committee_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if minutes_status is not None:
        items = [m for m in items if m["minutes_status"] == minutes_status]
    if approved_at is not None:
        items = [m for m in items
                 if m.get("minutes_approved_at_meeting_id") == approved_at]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(m) for m in page], limit, offset, total)


@bp.get("/governance/meetings/<meeting_id>")
def get_meeting(meeting_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("meetings", meeting_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/meetings/<meeting_id>/notice")
def post_notice(meeting_id):
    auth.authorize(["BoardClerk"])
    meeting = v.find("meetings", meeting_id)

    if meeting["status"] != "DRAFT":
        fail("ERR_INVALID_MEETING_STATE",
             "Notice may only be posted on a draft meeting.")

    lead_hours = calc.NOTICE_LEAD_HOURS[meeting["meeting_type"]]
    delta = (meeting["scheduled_start_utc"] - store.now()).total_seconds()
    if delta < lead_hours * 3600:
        fail("ERR_NOTICE_PERIOD_TOO_SHORT",
             "The statutory notice lead time has not been met.")

    now = store.now()
    set_fields(meeting, status="NOTICED", notice_posted_at=now,
               agenda_locked_at=now)
    for item in calc.meeting_items(meeting_id):
        if item["status"] == "PROPOSED":
            set_fields(item, status="POSTED")
    return resp.ok(store.serialize(meeting))


@bp.post("/governance/meetings/<meeting_id>/open")
def open_meeting(meeting_id):
    user_id, role = auth.authorize(["BoardPresident"])
    meeting = v.find("meetings", meeting_id)
    body = v.body()
    attending = v.req_id_list(body, "attending_member_ids")

    members = []
    for member_id in attending:
        members.append(v.find("board_members", member_id))

    auth.enforce_president(user_id, role)

    if meeting["status"] != "NOTICED":
        fail("ERR_INVALID_MEETING_STATE",
             "Only a noticed meeting may be called to order.")

    for member in members:
        if member["status"] != "SEATED":
            fail("ERR_MEMBER_NOT_SEATED",
                 "Trustee %s is not seated." % member["id"])

    quorum_required = store.meeting_quorum_required(meeting)
    if len(attending) < quorum_required:
        fail("ERR_QUORUM_NOT_MET", "Attendance is below the required quorum.")

    if store.now() < meeting["scheduled_start_utc"]:
        fail("ERR_MEETING_NOT_YET_DUE",
             "The meeting may not be opened before its scheduled start.")

    seated_count = len([m for m in db["board_members"].values()
                        if m["status"] == "SEATED"])
    set_fields(meeting, status="OPEN", opened_at=store.now(),
               seated_member_count_snapshot=seated_count,
               attending_member_ids=list(attending))
    calc.allocate_public_comment(meeting)
    return resp.ok(store.serialize(meeting))


@bp.post("/governance/meetings/<meeting_id>/adjourn")
def adjourn_meeting(meeting_id):
    auth.authorize(["BoardClerk"])
    meeting = v.find("meetings", meeting_id)

    if meeting["status"] != "OPEN":
        fail("ERR_INVALID_MEETING_STATE", "Only an open meeting may adjourn.")

    set_fields(meeting, status="ADJOURNED", adjourned_at=store.now())
    for item in calc.meeting_items(meeting_id):
        if item["status"] == "POSTED":
            set_fields(item, status="TABLED")
            calc.release_cards(item, ("GRANTED",))
    return resp.ok(store.serialize(meeting))


@bp.post("/governance/meetings/<meeting_id>/minutes")
def advance_minutes(meeting_id):
    auth.authorize(["BoardClerk"])
    meeting = v.find("meetings", meeting_id)
    body = v.body()
    action = v.req_enum(body, "action", ["DRAFT", "APPROVE"])
    approving_id = v.opt_id(body, "approving_meeting_id")

    if action == "APPROVE" and approving_id is None:
        fail("ERR_INVALID_REQUEST",
             "approving_meeting_id is required when action is APPROVE.")
    if action == "DRAFT" and approving_id is not None:
        fail("ERR_INVALID_REQUEST",
             "approving_meeting_id must be omitted when action is DRAFT.")

    approving = None
    if approving_id is not None:
        approving = v.find("meetings", approving_id)

    if action == "DRAFT":
        if meeting["minutes_status"] != "NOT_DRAFTED":
            fail("ERR_INVALID_MINUTES_STATE",
                 "The minutes have already been drafted.")
        if meeting["status"] != "ADJOURNED":
            fail("ERR_INVALID_MINUTES_STATE",
                 "The minutes may only be drafted after adjournment.")
        set_fields(meeting, minutes_status="DRAFTED")
        touch(meeting)
        return resp.ok(store.serialize(meeting))

    if meeting["minutes_status"] != "DRAFTED":
        fail("ERR_INVALID_MINUTES_STATE",
             "Only drafted minutes may be approved.")

    if approving["status"] != "OPEN":
        fail("ERR_INVALID_APPROVING_MEETING",
             "The approving meeting is not currently open.")
    if approving["id"] == meeting["id"]:
        fail("ERR_INVALID_APPROVING_MEETING",
             "Minutes may not be approved at their own meeting.")
    if approving["scheduled_start_utc"] <= meeting["scheduled_start_utc"]:
        fail("ERR_INVALID_APPROVING_MEETING",
             "The approving meeting must be scheduled strictly later.")

    set_fields(meeting, minutes_status="APPROVED",
               minutes_approved_at_meeting_id=approving["id"])
    touch(meeting)
    return resp.ok(store.serialize(meeting))
