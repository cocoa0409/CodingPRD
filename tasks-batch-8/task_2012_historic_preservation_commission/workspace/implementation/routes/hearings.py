"""Hearings and public comment (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE,
    ERR_NOTICE_WINDOW_TOO_SHORT, ERR_MEETING_AGENDA_FULL,
    ERR_COMMENT_PERIOD_CLOSED,
)
from middleware import get_caller, check_role_allowed, authorized, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response, get_one
from services.calculations import notice_window_ok
from services.core import new_record, touch, refresh_meeting_count
from util import CLOCK, fmt_dt
from validate import (
    get_body, req_str, req_enum, req_datetime, require_path_resource,
    require_body_ref,
)

bp = Blueprint("hearings", __name__, url_prefix="/preservation")

STAFF = ["PreservationStaff"]
COMMISSIONER = ["Commissioner"]
STANCES = {"SUPPORT", "OPPOSE", "NEUTRAL"}


@bp.post("/hearings")
def create_hearing():
    caller = get_caller()
    body = get_body()
    application_id = req_str(body, "application_id")
    meeting_id = req_str(body, "meeting_id")
    notice_posted_at = req_datetime(body, "notice_posted_at")
    check_role_allowed(caller, STAFF)
    app = require_body_ref("applications", application_id, "application_id")
    meeting = require_body_ref("meetings", meeting_id, "meeting_id")

    # Layer 5 (state): the transition is declared only for a COMMISSION-track
    # application in ACCEPTED — a STAFF-track ACCEPTED application fails here
    # too (PRD 3.4: "Scheduling a hearing for an application in any other
    # situation — including a STAFF-track ACCEPTED application — is rejected
    # with ERR_INVALID_STATE").
    if app["status"] != "ACCEPTED" or app.get("review_track") != "COMMISSION":
        raise_error(ERR_INVALID_STATE,
                    "hearing scheduling requires an ACCEPTED COMMISSION-track application, "
                    f"got {app['status']}/{app.get('review_track')}")
    # Layer 8 (temporal): fifteen clear days of notice, boundary inclusive.
    from util import parse_dt
    if not notice_window_ok(notice_posted_at, parse_dt(meeting["meeting_date"])):
        raise_error(ERR_NOTICE_WINDOW_TOO_SHORT,
                    "notice_posted_at must be no later than meeting_date - 15 days")
    # Layer 9 (structural): agenda capacity.
    if meeting["scheduled_hearing_count"] >= meeting["agenda_capacity"]:
        raise_error(ERR_MEETING_AGENDA_FULL, "the meeting agenda is at capacity")

    hearing = new_record("hearings", {
        "application_id": application_id,
        "meeting_id": meeting_id,
        "notice_posted_at": fmt_dt(notice_posted_at),
        "status": "SCHEDULED",
    })
    app["status"] = "HEARING_SCHEDULED"
    touch(app)
    refresh_meeting_count(meeting_id)
    return success_object(public(hearing), status=201)


@bp.get("/hearings")
def list_hearings():
    filters = {
        "application_id": request.args.get("application_id"),
        "meeting_id": request.args.get("meeting_id"),
        "status": request.args.get("status"),
    }
    return list_response("hearings", filters)


@bp.get("/hearings/<rid>")
def get_hearing(rid):
    return get_one("hearings", rid)


@bp.post("/hearings/<rid>/open")
def open_hearing(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, COMMISSIONER)
    hearing = require_path_resource("hearings", rid)
    if hearing["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"open requires SCHEDULED, got {hearing['status']}")
    app = db["applications"].get(hearing["application_id"])
    if app is None or app["status"] != "HEARING_SCHEDULED":
        raise_error(ERR_INVALID_STATE, "the application is not HEARING_SCHEDULED")
    hearing["status"] = "OPENED"
    touch(hearing)
    app["status"] = "HEARING_OPEN"
    touch(app)
    return success_object(public(hearing))


@bp.post("/hearings/<rid>/continue")
def continue_hearing(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, COMMISSIONER)
    hearing = require_path_resource("hearings", rid)
    if hearing["status"] not in ("SCHEDULED", "OPENED"):
        raise_error(ERR_INVALID_STATE,
                    f"continue requires SCHEDULED or OPENED, got {hearing['status']}")
    app = db["applications"].get(hearing["application_id"])
    hearing["status"] = "CONTINUED"
    touch(hearing)
    if app is not None and app["status"] in ("HEARING_SCHEDULED", "HEARING_OPEN"):
        app["status"] = "HEARING_DEFERRED"
        touch(app)
    refresh_meeting_count(hearing["meeting_id"])  # frees the agenda slot
    return success_object(public(hearing))


@bp.post("/hearings/<rid>/reschedule")
def reschedule_hearing(rid):
    caller = get_caller()
    body = get_body()
    meeting_id = req_str(body, "meeting_id")
    notice_posted_at = req_datetime(body, "notice_posted_at")
    check_role_allowed(caller, STAFF)
    hearing = require_path_resource("hearings", rid)
    meeting = require_body_ref("meetings", meeting_id, "meeting_id")
    # Layer 5 (state) beats the temporal window (layer 8).
    if hearing["status"] != "CONTINUED":
        raise_error(ERR_INVALID_STATE,
                    f"reschedule requires CONTINUED, got {hearing['status']}")
    from util import parse_dt
    if not notice_window_ok(notice_posted_at, parse_dt(meeting["meeting_date"])):
        raise_error(ERR_NOTICE_WINDOW_TOO_SHORT,
                    "notice_posted_at must be no later than meeting_date - 15 days")
    if meeting["scheduled_hearing_count"] >= meeting["agenda_capacity"]:
        raise_error(ERR_MEETING_AGENDA_FULL, "the meeting agenda is at capacity")

    hearing["meeting_id"] = meeting_id
    hearing["notice_posted_at"] = fmt_dt(notice_posted_at)
    hearing["status"] = "SCHEDULED"
    touch(hearing)
    refresh_meeting_count(meeting_id)
    app = db["applications"].get(hearing["application_id"])
    if app is not None and app["status"] == "HEARING_DEFERRED":
        app["status"] = "HEARING_SCHEDULED"
        touch(app)
    return success_object(public(hearing))


@bp.post("/hearings/<rid>/comments")
def create_comment(rid):
    caller = get_caller()
    body = get_body()
    commenter_name = req_str(body, "commenter_name")
    stance = req_enum(body, "stance", STANCES)
    comment_text = req_str(body, "comment_text")
    check_role_allowed(caller, ALL_ROLES)
    hearing = require_path_resource("hearings", rid)
    # The comment period is open only while the hearing is SCHEDULED or CONTINUED.
    if hearing["status"] not in ("SCHEDULED", "CONTINUED"):
        raise_error(ERR_COMMENT_PERIOD_CLOSED,
                    "the public comment period closed when the hearing opened")
    rec = new_record("comments", {
        "hearing_id": rid,
        "commenter_name": commenter_name,
        "stance": stance,
        "comment_text": comment_text,
        "submitted_at": CLOCK.now_iso(),
    }, with_version=False)
    return success_object(public(rec), status=201)


@bp.get("/hearings/<rid>/comments")
def list_comments(rid):
    authorized(ALL_ROLES)
    require_path_resource("hearings", rid)
    items = [c for c in db["comments"].values() if c.get("hearing_id") == rid]
    return list_response("comments", items=items)
