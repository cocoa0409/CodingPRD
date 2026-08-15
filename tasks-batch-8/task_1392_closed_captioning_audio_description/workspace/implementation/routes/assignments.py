"""LiveAssignment endpoints (PRD §3.7): offer create (OCC + auto-offer),
accept, decline, check-in, preempt, mark-no-show."""
from datetime import timedelta
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, touch
from errors import (
    ApiError,
    ERR_CAPACITY_EXCEEDED,
    ERR_CHECKIN_WINDOW_CLOSED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_NO_ELIGIBLE_STENOGRAPHER,
    ERR_OFFER_EXPIRED,
    ERR_STALE_LIVE_EVENT_VERSION,
    ERR_STENOGRAPHER_DOUBLE_BOOKED,
    invalid_transition,
    not_found,
    validation,
)
from respond import list_response, ok_object
from services import livelog, workflow
from util import is_int

bp = Blueprint("assignments", __name__)

PREEMPTION_REASONS = {"SCHEDULER_OVERRIDE", "EMERGENCY_REBOOK", "CLIENT_REQUEST"}


def get_assignment(assignment_id):
    a = DB.assignments.get(assignment_id)
    if a is None:
        raise not_found("Live assignment not found")
    return a


@bp.post("/caption-ad/live-events/<liveEventId>/assignments")
@guarded({"Scheduler"})
def create_assignment(liveEventId, _user_id, _role):
    event = DB.live_events.get(liveEventId)
    if event is None:
        raise not_found("Live event not found")
    data = body()
    steno_id = data.get("stenographer_id")
    steno = None
    if steno_id is not None:
        if not isinstance(steno_id, str):
            raise validation("Field 'stenographer_id' must be a string")
        steno = DB.stenographers.get(steno_id)
        if steno is None:
            raise not_found("Referenced stenographer_id does not exist")
    expected = data.get("expected_live_event_version")
    if not is_int(expected):
        raise validation("Field 'expected_live_event_version' is required and must be an integer")
    # OCC (priority 6) precedes capacity/geometry checks (priority 10).
    if expected != event["version"]:
        raise ApiError(ERR_STALE_LIVE_EVENT_VERSION, 412, "Stale live event version")
    if steno is not None:
        # Direct offer: the named stenographer must be eligible, then overlap
        # and capacity are checked at create time.
        if not livelog.eligible_basic(steno, event):
            raise ApiError(
                ERR_NO_ELIGIBLE_STENOGRAPHER,
                422,
                "Stenographer must be ACTIVE, certification-matched, and certified through the event end",
            )
        if livelog.has_overlap_conflict(steno["id"], event):
            raise ApiError(ERR_STENOGRAPHER_DOUBLE_BOOKED, 409, "Occupancy windows conflict for this stenographer")
        day = event["start_at"].date()
        if livelog.committed_minutes(steno["id"], day) + livelog.booked_minutes(event) > steno["max_daily_live_minutes"]:
            raise ApiError(ERR_CAPACITY_EXCEEDED, 422, "Daily committed-minutes cap would be exceeded")
        rec = workflow.create_offer(event, steno["id"], "MANUAL")
    else:
        # Auto-offer: run the selector; an empty pool rejects a direct create.
        winner = livelog.auto_offer_select(event)
        if winner is None:
            raise ApiError(ERR_NO_ELIGIBLE_STENOGRAPHER, 422, "No eligible stenographer in the candidate pool")
        rec = workflow.create_offer(event, winner["id"], "AUTO_OFFER")
    return ok_object(serialize.assignment(rec), status=201)


@bp.get("/caption-ad/live-assignments")
@guarded(set(ALL_ROLES))
def list_assignments(_user_id, _role):
    records = list(DB.assignments.values())
    for param, field in (
        ("live_event_id", "live_event_id"),
        ("stenographer_id", "stenographer_id"),
        ("assignment_status", "assignment_status"),
    ):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.assignment)


@bp.get("/caption-ad/live-assignments/<assignmentId>")
@guarded(set(ALL_ROLES))
def get_one_assignment(assignmentId, _user_id, _role):
    return ok_object(serialize.assignment(get_assignment(assignmentId)))


def _load_owned(assignmentId, user_id):
    a = get_assignment(assignmentId)
    if a["stenographer_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "A stenographer may act only on own assignments")
    return a


@bp.post("/caption-ad/live-assignments/<assignmentId>/accept")
@guarded({"Stenographer"})
def accept_assignment(assignmentId, _user_id, _role):
    a = _load_owned(assignmentId, _user_id)
    if a["assignment_status"] != "OFFERED":
        raise invalid_transition("Only an OFFERED assignment can be accepted")
    t = now()
    if t >= a["offer_expires_at"]:
        raise ApiError(ERR_OFFER_EXPIRED, 409, "Accept attempted at or after offer_expires_at")
    event = DB.live_events[a["live_event_id"]]
    steno = DB.stenographers[a["stenographer_id"]]
    # Overlap and capacity re-run at accept time.
    if livelog.has_overlap_conflict(a["stenographer_id"], event):
        raise ApiError(ERR_STENOGRAPHER_DOUBLE_BOOKED, 409, "Occupancy windows conflict for this stenographer")
    day = event["start_at"].date()
    if livelog.committed_minutes(a["stenographer_id"], day) + a["booked_minutes"] > steno["max_daily_live_minutes"]:
        raise ApiError(ERR_CAPACITY_EXCEEDED, 422, "Daily committed-minutes cap would be exceeded")
    a["assignment_status"] = "ACCEPTED"
    touch(a)
    return ok_object(serialize.assignment(a))


@bp.post("/caption-ad/live-assignments/<assignmentId>/decline")
@guarded({"Stenographer"})
def decline_assignment(assignmentId, _user_id, _role):
    a = _load_owned(assignmentId, _user_id)
    if a["assignment_status"] != "OFFERED":
        raise invalid_transition("Only an OFFERED assignment can be declined")
    a["assignment_status"] = "DECLINED"
    touch(a)
    # Cascade: selector runs with the decliner excluded (exclusion memory);
    # an empty pool silently creates nothing.
    event = DB.live_events[a["live_event_id"]]
    workflow.run_auto_offer_cascade(event)
    return ok_object(serialize.assignment(a))


@bp.post("/caption-ad/live-assignments/<assignmentId>/check-in")
@guarded({"Stenographer"})
def check_in_assignment(assignmentId, _user_id, _role):
    a = _load_owned(assignmentId, _user_id)
    if a["assignment_status"] != "ACCEPTED":
        raise invalid_transition("Only an ACCEPTED assignment can check in")
    event = DB.live_events[a["live_event_id"]]
    t = now()
    # Window [start-30min, start-10min], both bounds inclusive.
    if not (event["start_at"] - timedelta(minutes=30) <= t <= event["start_at"] - timedelta(minutes=10)):
        raise ApiError(ERR_CHECKIN_WINDOW_CLOSED, 409, "Check-in outside [start-30min, start-10min]")
    a["assignment_status"] = "CONFIRMED"
    touch(a)
    # The first assignment to reach CONFIRMED briefs the event.
    if event["event_status"] == "SCHEDULED":
        event["event_status"] = "BRIEFED"
        touch(event)
    return ok_object(serialize.assignment(a))


@bp.post("/caption-ad/live-assignments/<assignmentId>/preempt")
@guarded({"Scheduler"})
def preempt_assignment(assignmentId, _user_id, _role):
    a = get_assignment(assignmentId)
    reason = body().get("preemption_reason")
    if reason not in PREEMPTION_REASONS:
        raise validation("Field 'preemption_reason' must be SCHEDULER_OVERRIDE, EMERGENCY_REBOOK, or CLIENT_REQUEST")
    if a["assignment_status"] not in ("ACCEPTED", "CONFIRMED"):
        raise invalid_transition("Only an ACCEPTED or CONFIRMED assignment can be preempted")
    event = DB.live_events[a["live_event_id"]]
    steno = DB.stenographers[a["stenographer_id"]]
    a["assignment_status"] = "PREEMPTED"
    a["preemption_reason"] = reason
    touch(a)
    # Preemption compensates the displaced stenographer with make-up minutes.
    steno["make_up_minutes_credited"] += a["booked_minutes"]
    touch(steno)
    workflow.maybe_debrief_event(event)
    # Cascade runs excluding the preempted stenographer and all prior
    # DECLINED/PREEMPTED/NO_SHOW stenographers (selector exclusion memory).
    workflow.run_auto_offer_cascade(event)
    return ok_object(serialize.assignment(a))


@bp.post("/caption-ad/live-assignments/<assignmentId>/mark-no-show")
@guarded({"Scheduler"})
def mark_no_show(assignmentId, _user_id, _role):
    a = get_assignment(assignmentId)
    if a["assignment_status"] not in ("ACCEPTED", "CONFIRMED"):
        raise invalid_transition("Only an ACCEPTED or CONFIRMED assignment can be marked no-show")
    event = DB.live_events[a["live_event_id"]]
    if now() < event["start_at"]:
        raise invalid_transition("A no-show can only be marked at or after the event start")
    steno = DB.stenographers[a["stenographer_id"]]
    a["assignment_status"] = "NO_SHOW"
    touch(a)
    steno["no_show_count"] += 1
    touch(steno)
    # No auto-offer cascade on no-show (unlike preemption).
    workflow.maybe_debrief_event(event)
    return ok_object(serialize.assignment(a))
