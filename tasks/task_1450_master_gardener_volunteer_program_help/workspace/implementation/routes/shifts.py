"""Shift, ShiftSignup, and Inquiry endpoints."""

from datetime import timedelta
from flask import request, Blueprint

import db
import util
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("shifts", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]

SHIFT_KINDS = ("HELP_DESK", "OUTREACH")
INQUIRY_CATEGORIES = ("PLANT_ID", "PEST", "PLANT_DISEASE", "SOIL", "GENERAL")


def get_shift_or_404(shift_id):
    s = db.shifts.get(shift_id)
    if s is None:
        raise_err("ERR_NOT_FOUND", "Shift not found")
    return s


def get_signup_or_404(signup_id):
    s = db.shift_signups.get(signup_id)
    if s is None:
        raise_err("ERR_NOT_FOUND", "ShiftSignup not found")
    return s


# =====================================================================
# Shift CRUD + lifecycle
# =====================================================================

@bp.route("/shifts", methods=["POST"])
def create_shift():
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("cycle_id", "kind", "location", "start_time", "end_time", "capacity"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not isinstance(body["cycle_id"], str):
        raise_err("ERR_INVALID_REQUEST", "cycle_id must be a string")
    if body["kind"] not in SHIFT_KINDS:
        raise_err("ERR_INVALID_REQUEST", "kind must be HELP_DESK or OUTREACH")
    if not isinstance(body["location"], str) or not body["location"]:
        raise_err("ERR_INVALID_REQUEST", "location must be a non-empty string")
    if not isinstance(body["start_time"], str) or not util.is_iso_datetime(body["start_time"]):
        raise_err("ERR_INVALID_REQUEST", "start_time must be an ISO 8601 datetime")
    if not isinstance(body["end_time"], str) or not util.is_iso_datetime(body["end_time"]):
        raise_err("ERR_INVALID_REQUEST", "end_time must be an ISO 8601 datetime")
    if not isinstance(body["capacity"], int) or isinstance(body["capacity"], bool):
        raise_err("ERR_INVALID_REQUEST", "capacity must be an integer")
    start = util.parse_dt(body["start_time"])
    end = util.parse_dt(body["end_time"])
    if end <= start:
        raise_err("ERR_INVALID_FIELD_VALUE", "end_time must be strictly after start_time")
    if body["capacity"] < 1 or body["capacity"] > 20:
        raise_err("ERR_INVALID_FIELD_VALUE", "capacity must be 1..20")

    cycle = db.program_cycles.get(body["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "cycle_id does not resolve")
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Shift creation requires an OPEN cycle")

    # overlap rule A: half-open location conflict, non-CANCELLED shifts
    for s in db.shifts.values():
        if s["location"] == body["location"] and s["status"] != "CANCELLED":
            ex_start = util.parse_dt(s["start_time"])
            ex_end = util.parse_dt(s["end_time"])
            if start < ex_end and ex_start < end:
                raise_err("ERR_SHIFT_LOCATION_CONFLICT",
                          "A non-CANCELLED shift at this location overlaps the requested window")

    shift = util.new_resource({
        "cycle_id": body["cycle_id"],
        "kind": body["kind"],
        "location": body["location"],
        "start_time": body["start_time"],
        "end_time": body["end_time"],
        "capacity": body["capacity"],
        "filled_count": 0,
        "status": "OPEN",
    })
    db.shifts[shift["id"]] = shift
    return success_object(shift, 201)


@bp.route("/shifts", methods=["GET"])
def list_shifts():
    auth_context(ALL_ROLES)
    items = list(db.shifts.values())
    for param in ("cycle_id", "kind", "location", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/shifts/<shiftId>", methods=["GET"])
def get_shift(shiftId):
    auth_context(ALL_ROLES)
    return success_object(get_shift_or_404(shiftId))


@bp.route("/shifts/<shiftId>/cancel", methods=["POST"])
def cancel_shift(shiftId):
    auth_context(PC)
    shift = get_shift_or_404(shiftId)
    if shift["status"] not in ("OPEN", "FULL"):
        raise_err("ERR_SHIFT_NOT_CANCELLABLE", "Cancel requires an OPEN or FULL shift")
    shift["status"] = "CANCELLED"
    # cascade: SIGNED_UP signups -> CANCELLED; no FULL->OPEN revert (terminal)
    for s in db.shift_signups.values():
        if s["shift_id"] == shift["id"] and s["status"] == "SIGNED_UP":
            s["status"] = "CANCELLED"
            util.touch(s)
    shift["filled_count"] = 0
    util.touch(shift)
    return success_object(shift)


@bp.route("/shifts/<shiftId>/complete", methods=["POST"])
def complete_shift(shiftId):
    auth_context(PC)
    shift = get_shift_or_404(shiftId)
    if shift["status"] not in ("OPEN", "FULL"):
        raise_err("ERR_INVALID_SHIFT_STATE", "Complete requires an OPEN or FULL shift")
    clock = util.logical_clock()
    if clock < util.parse_dt(shift["end_time"]):
        raise_err("ERR_SHIFT_NOT_ENDED", "Shift has not ended yet")
    shift["status"] = "COMPLETED"
    util.touch(shift)
    return success_object(shift)


# =====================================================================
# ShiftSignup endpoints
# =====================================================================

TRAVEL_BUFFER_MINUTES = 30
NO_SHOW_LIMIT = 3


@bp.route("/shifts/<shiftId>/signups", methods=["POST"])
def create_signup(shiftId):
    user_id, role = auth_context(["Volunteer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "volunteer_id" not in body:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: volunteer_id")
    if not isinstance(body["volunteer_id"], str):
        raise_err("ERR_INVALID_REQUEST", "volunteer_id must be a string")

    # path id resolves first
    shift = db.shifts.get(shiftId)
    if shift is None:
        raise_err("ERR_NOT_FOUND", "Shift not found")
    vol = db.volunteers.get(body["volunteer_id"])
    if vol is None:
        raise_err("ERR_NOT_FOUND", "volunteer_id does not resolve")
    # ownership
    if user_id != vol["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Volunteers may only sign themselves up")
    # state tier
    if vol["status"] != "ACTIVE":
        raise_err("ERR_VOLUNTEER_NOT_ACTIVE", "Volunteer must be ACTIVE to sign up")
    if shift["status"] != "OPEN":
        raise_err("ERR_SHIFT_NOT_OPEN", "Signup requires an OPEN shift")

    clock = util.logical_clock()
    start = util.parse_dt(shift["start_time"])
    end = util.parse_dt(shift["end_time"])

    # uniqueness / capacity / strikes (priority 10)
    for s in db.shift_signups.values():
        if s["shift_id"] == shift["id"] and s["volunteer_id"] == vol["id"] and s["status"] == "SIGNED_UP":
            raise_err("ERR_DUPLICATE_SIGNUP", "A SIGNED_UP signup already exists for this volunteer and shift")
    if vol["no_show_strikes"] >= NO_SHOW_LIMIT:
        raise_err("ERR_NO_SHOW_LIMIT_REACHED", "Volunteer has reached the no-show strike limit")
    # signup travel-buffer overlap (rule B) against SIGNED_UP shifts
    for s in db.shift_signups.values():
        if s["volunteer_id"] == vol["id"] and s["status"] == "SIGNED_UP":
            other = db.shifts.get(s["shift_id"])
            if other is None:
                continue
            o_start = util.parse_dt(other["start_time"])
            o_end = util.parse_dt(other["end_time"])
            buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES) if shift["location"] != other["location"] else timedelta(0)
            if not (start >= o_end + buffer or o_start >= end + buffer):
                raise_err("ERR_SIGNUP_SCHEDULE_CONFLICT", "Travel-buffer overlap with an existing signup")

    # temporal (priority 11): clock strictly before start
    if clock >= start:
        raise_err("ERR_SIGNUP_WINDOW_CLOSED", "Signup window closed: logical clock is at or after shift start")

    signup = util.new_resource({
        "shift_id": shift["id"],
        "volunteer_id": vol["id"],
        "status": "SIGNED_UP",
        "signed_up_at": util.logical_clock_iso(),
        "completed_entry_id": None,
    })
    db.shift_signups[signup["id"]] = signup
    shift["filled_count"] += 1
    if shift["filled_count"] >= shift["capacity"]:
        shift["status"] = "FULL"
    util.touch(shift)
    return success_object(signup, 201)


@bp.route("/shift-signups", methods=["GET"])
def list_signups():
    auth_context(ALL_ROLES)
    items = list(db.shift_signups.values())
    for param in ("shift_id", "volunteer_id", "status", "completed_entry_id"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/shift-signups/<signupId>", methods=["GET"])
def get_signup(signupId):
    auth_context(ALL_ROLES)
    return success_object(get_signup_or_404(signupId))


@bp.route("/shift-signups/<signupId>/cancel", methods=["POST"])
def cancel_signup(signupId):
    user_id, role = auth_context(["ProgramCoordinator", "Volunteer"])
    signup = get_signup_or_404(signupId)
    if role == "Volunteer" and user_id != signup["volunteer_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Volunteers may only cancel their own signups")
    if signup["status"] != "SIGNED_UP":
        raise_err("ERR_SIGNUP_NOT_SIGNED_UP", "Cancel requires a SIGNED_UP signup")
    shift = db.shifts.get(signup["shift_id"])
    if shift is None:
        raise_err("ERR_NOT_FOUND", "Signup's shift not found")
    clock = util.logical_clock()
    if clock >= util.parse_dt(shift["start_time"]):
        raise_err("ERR_CANCELLATION_WINDOW_CLOSED", "Cancellation window closed at shift start")
    signup["status"] = "CANCELLED"
    util.touch(signup)
    shift["filled_count"] = max(0, shift["filled_count"] - 1)
    if shift["status"] == "FULL":
        shift["status"] = "OPEN"
    util.touch(shift)
    return success_object(signup)


@bp.route("/shift-signups/<signupId>/complete", methods=["POST"])
def complete_signup(signupId):
    auth_context(PC)
    signup = get_signup_or_404(signupId)
    # priority 8: target resource's own state first
    if signup["status"] != "SIGNED_UP":
        raise_err("ERR_SIGNUP_NOT_SIGNED_UP", "Complete requires a SIGNED_UP signup")
    shift = db.shifts.get(signup["shift_id"])
    if shift is None:
        raise_err("ERR_NOT_FOUND", "Signup's shift not found")
    if shift["status"] != "COMPLETED":
        raise_err("ERR_SHIFT_NOT_COMPLETED", "Parent shift must be COMPLETED")
    hours = calc.shift_credit_hours(shift)
    activity_type = "HELP_DESK" if shift["kind"] == "HELP_DESK" else "OUTREACH"
    activity_date = util.parse_dt(shift["start_time"]).date().isoformat()
    entry = util.new_resource({
        "volunteer_id": signup["volunteer_id"],
        "cycle_id": shift["cycle_id"],
        "entry_kind": "SERVICE",
        "activity_type": activity_type,
        "provider": None,
        "title": None,
        "activity_date": activity_date,
        "hours": float(hours),
        "status": "PENDING",
        "source_type": "SHIFT",
        "source_id": shift["id"],
        "note": None,
        "decided_at": None,
    })
    db.credit_entries[entry["id"]] = entry
    signup["status"] = "COMPLETED"
    signup["completed_entry_id"] = entry["id"]
    util.touch(signup)
    return success_object(signup)


@bp.route("/shift-signups/<signupId>/mark-no-show", methods=["POST"])
def mark_no_show(signupId):
    auth_context(PC)
    signup = get_signup_or_404(signupId)
    if signup["status"] != "SIGNED_UP":
        raise_err("ERR_SIGNUP_NOT_SIGNED_UP", "Mark-no-show requires a SIGNED_UP signup")
    shift = db.shifts.get(signup["shift_id"])
    if shift is None:
        raise_err("ERR_NOT_FOUND", "Signup's shift not found")
    if shift["status"] != "COMPLETED":
        raise_err("ERR_SHIFT_NOT_COMPLETED", "Parent shift must be COMPLETED")
    signup["status"] = "NO_SHOW"
    util.touch(signup)
    vol = db.volunteers.get(signup["volunteer_id"])
    if vol is not None:
        vol["no_show_strikes"] += 1
        util.touch(vol)
    return success_object(signup)


# =====================================================================
# Inquiry endpoints
# =====================================================================

@bp.route("/shifts/<shiftId>/inquiries", methods=["POST"])
def create_inquiry(shiftId):
    user_id, role = auth_context(["Volunteer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("volunteer_id", "subject", "contact_name", "details"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
        if not isinstance(body[f], str) or not body[f]:
            raise_err("ERR_INVALID_REQUEST", f"{f} must be a non-empty string")
    follow_up_of_id = body.get("follow_up_of_id")

    shift = db.shifts.get(shiftId)
    if shift is None:
        raise_err("ERR_NOT_FOUND", "Shift not found")
    vol = db.volunteers.get(body["volunteer_id"])
    if vol is None:
        raise_err("ERR_NOT_FOUND", "volunteer_id does not resolve")
    if follow_up_of_id is not None:
        target = db.inquiries.get(follow_up_of_id)
        if target is None:
            raise_err("ERR_NOT_FOUND", "follow_up_of_id does not resolve")
    # ownership
    if user_id != vol["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Inquiries may only be logged as oneself")
    # cross-entity referential (shift kind, signup) — priority 12; clock window priority 11
    # temporal window first unless follow-up
    clock = util.logical_clock()
    if follow_up_of_id is None:
        start = util.parse_dt(shift["start_time"])
        end = util.parse_dt(shift["end_time"])
        if not (start <= clock < end):
            raise_err("ERR_OUTSIDE_SHIFT_WINDOW", "Logical clock is outside the shift window")
    if shift["kind"] != "HELP_DESK":
        raise_err("ERR_SHIFT_KIND_NOT_HELP_DESK", "Inquiries may only be logged on HELP_DESK shifts")
    has_signup = any(s for s in db.shift_signups.values()
                     if s["shift_id"] == shift["id"] and s["volunteer_id"] == vol["id"]
                     and s["status"] in ("SIGNED_UP", "COMPLETED"))
    if not has_signup:
        raise_err("ERR_NO_SHIFT_SIGNUP", "The logging volunteer has no signup on this shift")
    if follow_up_of_id is not None:
        if target["status"] != "CLOSED":
            raise_err("ERR_FOLLOW_UP_TARGET_NOT_CLOSED", "Follow-up target must be CLOSED")

    inquiry = util.new_resource({
        "shift_id": shift["id"],
        "volunteer_id": vol["id"],
        "subject": body["subject"],
        "contact_name": body["contact_name"],
        "details": body["details"],
        "category": None,
        "status": "LOGGED",
        "resolution": "NONE",
        "answer_text": None,
        "follow_up_of_id": follow_up_of_id,
        "resolved_at": None,
    })
    db.inquiries[inquiry["id"]] = inquiry
    return success_object(inquiry, 201)


@bp.route("/inquiries", methods=["GET"])
def list_inquiries():
    auth_context(ALL_ROLES)
    items = list(db.inquiries.values())
    for param in ("shift_id", "volunteer_id", "status", "category", "follow_up_of_id"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


def get_inquiry_or_404(inquiry_id):
    i = db.inquiries.get(inquiry_id)
    if i is None:
        raise_err("ERR_NOT_FOUND", "Inquiry not found")
    return i


@bp.route("/inquiries/<inquiryId>", methods=["GET"])
def get_inquiry(inquiryId):
    auth_context(ALL_ROLES)
    return success_object(get_inquiry_or_404(inquiryId))


@bp.route("/inquiries/<inquiryId>/triage", methods=["POST"])
def triage_inquiry(inquiryId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "category" not in body:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: category")
    if body["category"] not in INQUIRY_CATEGORIES:
        raise_err("ERR_INVALID_REQUEST", "category is not a valid enum member")
    inquiry = get_inquiry_or_404(inquiryId)
    if inquiry["status"] != "LOGGED":
        raise_err("ERR_INQUIRY_NOT_LOGGED", "Triage requires a LOGGED inquiry")
    inquiry["category"] = body["category"]
    inquiry["status"] = "TRIAGED"
    util.touch(inquiry)
    return success_object(inquiry)


@bp.route("/inquiries/<inquiryId>/answer", methods=["POST"])
def answer_inquiry(inquiryId):
    user_id, role = auth_context(["Volunteer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "answer_text" not in body or not isinstance(body.get("answer_text"), str):
        raise_err("ERR_INVALID_REQUEST", "answer_text is required")
    inquiry = get_inquiry_or_404(inquiryId)
    # ownership (priority 5) precedes state (priority 8)
    if user_id != inquiry["volunteer_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the logging volunteer may answer this inquiry")
    if inquiry["status"] != "TRIAGED":
        raise_err("ERR_INQUIRY_NOT_TRIAGED", "Answer requires a TRIAGED inquiry")
    inquiry["status"] = "CLOSED"
    inquiry["resolution"] = "ANSWERED_AT_DESK"
    inquiry["answer_text"] = body["answer_text"]
    inquiry["resolved_at"] = util.logical_clock_iso()
    util.touch(inquiry)
    return success_object(inquiry)
