"""SecurityEvent endpoints: creation, profile patch and the night lifecycle."""

from datetime import timedelta

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate, plain_action
from db import db, make_record, now, parse_iso, touch
from errors import ApiError
from response import object_response
from routes._common import get_event, get_venue, match_filters, paginated

bp = Blueprint("events", __name__)

EVENT_TYPES = ("CONCERT", "SPORTING", "FESTIVAL", "CONVENTION", "CIVIC_PROTEST")
EVENT_STATUSES = (
    "PLANNING",
    "RISK_ASSESSED",
    "STAFFED",
    "BRIEFED",
    "DOORS_OPEN",
    "IN_PROGRESS",
    "SUSPENDED",
    "CLOSED",
    "DEBRIEFED",
)
GATE_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
LIFECYCLE_ACTIONS = ("BRIEF", "DOORS_OPEN", "START", "SUSPEND", "RESUME", "CLOSE")

READ_ROLES = {
    "SecurityDirector",
    "RiskAnalyst",
    "StaffingCoordinator",
    "CredentialAuditor",
    "IncidentCommander",
    "PostSupervisor",
    "SystemOperator",
}
LIST_ROLES = {"SecurityDirector", "RiskAnalyst", "StaffingCoordinator", "IncidentCommander"}


@bp.post("/security-events")
def create_event():
    authenticate({"SecurityDirector"})
    payload = valid.body()
    venue_id = valid.req_string(payload, "venue_id")
    event_name = valid.req_string(payload, "event_name")
    event_type = valid.req_enum(payload, "event_type", EVENT_TYPES)
    doors_open = valid.req_datetime(payload, "doors_open_at")
    event_start = valid.req_datetime(payload, "event_start_at")
    event_end = valid.req_datetime(payload, "event_end_at")
    if event_start[1] <= doors_open[1]:
        valid.bad("Field 'event_start_at' must be strictly after 'doors_open_at'.")
    if event_end[1] <= event_start[1]:
        valid.bad("Field 'event_end_at' must be strictly after 'event_start_at'.")
    expected_attendance = valid.req_int(payload, "expected_attendance", minimum=1)
    ticketed_attendance = valid.opt_int(payload, "ticketed_attendance", minimum=1)
    alcohol_served = valid.opt_bool(payload, "alcohol_served", default=False)
    vip_present = valid.opt_bool(payload, "vip_present", default=False)

    venue = get_venue(venue_id)
    if expected_attendance > venue["gross_capacity"]:
        valid.bad("Field 'expected_attendance' may not exceed the venue's gross_capacity.")
    if ticketed_attendance is not None and ticketed_attendance > venue["gross_capacity"]:
        valid.bad("Field 'ticketed_attendance' may not exceed the venue's gross_capacity.")

    record = make_record(
        {
            "venue_id": venue["id"],
            "event_name": event_name,
            "event_type": event_type,
            "doors_open_at": doors_open[0],
            "event_start_at": event_start[0],
            "event_end_at": event_end[0],
            "expected_attendance": expected_attendance,
            "ticketed_attendance": ticketed_attendance,
            "alcohol_served": alcohol_served,
            "vip_present": vip_present,
            "status": "PLANNING",
            "ingress_status": "NORMAL",
            "gate_posture": "OPEN",
            "open_critical_incident_count": 0,
        }
    )
    db.events[record["id"]] = record
    engine.recompute_event(record)
    return object_response(serial.event(record), 201)


@bp.get("/security-events/<event_id>")
def read_event(event_id):
    authenticate(READ_ROLES)
    event = get_event(event_id)
    return object_response(serial.event(event))


@bp.get("/security-events")
def list_events():
    authenticate(LIST_ROLES)
    filters = {
        "venue_id": valid.query_string("venue_id"),
        "status": valid.query_enum("status", EVENT_STATUSES),
        "gate_posture": valid.query_enum("gate_posture", GATE_POSTURES),
    }
    records = [e for e in db.events.values() if match_filters(e, filters)]
    return paginated(records, serial.event)


@bp.patch("/security-events/<event_id>")
def patch_event(event_id):
    authenticate({"SecurityDirector"})
    payload = valid.body()
    expected_version = valid.req_int(payload, "expected_event_version")
    ticketed_attendance = valid.opt_int(payload, "ticketed_attendance", minimum=1)
    alcohol_served = valid.opt_bool(payload, "alcohol_served")
    vip_present = valid.opt_bool(payload, "vip_present")

    event = get_event(event_id)
    venue = db.venues.get(event["venue_id"])
    if (
        ticketed_attendance is not None
        and venue is not None
        and ticketed_attendance > venue["gross_capacity"]
    ):
        valid.bad("Field 'ticketed_attendance' may not exceed the venue's gross_capacity.")

    if expected_version != event.get("version"):
        raise ApiError("ERR_STALE_EVENT_VERSION")

    if ticketed_attendance is not None:
        event["ticketed_attendance"] = ticketed_attendance
    if alcohol_served is not None:
        event["alcohol_served"] = alcohol_served
    if vip_present is not None:
        event["vip_present"] = vip_present
    engine.recompute_event(event)
    touch(event)
    return object_response(serial.event(event))


def _require_status(event, allowed):
    if event.get("status") not in allowed:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Event status '%s' has no such outgoing transition." % event.get("status"),
        )


def _require_gate(event):
    if event.get("gate_posture") == "FROZEN":
        raise ApiError("ERR_EVENT_GATE_FROZEN")


@bp.post("/security-events/<event_id>/lifecycle")
def event_lifecycle(event_id):
    authenticate({"SecurityDirector"})
    payload = valid.body()
    action = plain_action(payload, LIFECYCLE_ACTIONS)
    valid.opt_string(payload, "note")

    event = get_event(event_id)
    plan = engine.current_plan(event["id"])

    if action == "BRIEF":
        _require_status(event, ("STAFFED",))
        if plan is None or plan.get("status") != "ACTIVATED":
            raise ApiError("ERR_INVALID_STATE", "The current plan is not ACTIVATED.")
        for assignment in engine.plan_committed_rows(plan["id"]):
            if (
                assignment.get("assignment_status") == "CONFIRMED"
                and assignment.get("duty_status") == "PENDING_BRIEF"
            ):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Every confirmed assignment must be briefed before the event is briefed.",
                )
        _require_gate(event)
        if plan.get("readiness_posture") != "READY":
            raise ApiError("ERR_PLAN_NOT_READY")
        event["status"] = "BRIEFED"

    elif action == "DOORS_OPEN":
        _require_status(event, ("BRIEFED",))
        _require_gate(event)
        _check_exit_posts(plan)
        _check_screening_capacity(event, plan)
        clock = now()
        doors_open_at = parse_iso(event["doors_open_at"])
        if clock < doors_open_at - timedelta(hours=1):
            raise ApiError("ERR_DOORS_OPEN_TOO_EARLY")
        event["status"] = "DOORS_OPEN"
        event["ingress_status"] = "NORMAL"

    elif action == "START":
        _require_status(event, ("DOORS_OPEN",))
        if now() < parse_iso(event["event_start_at"]):
            raise ApiError("ERR_INVALID_STATE", "The logical clock has not reached event_start_at.")
        event["status"] = "IN_PROGRESS"

    elif action == "SUSPEND":
        _require_status(event, ("IN_PROGRESS",))
        event["status"] = "SUSPENDED"
        event["ingress_status"] = "HOLD"
        engine.hold_open_lanes(event)

    elif action == "RESUME":
        _require_status(event, ("SUSPENDED",))
        if engine.open_critical_incident_count(event["id"]) != 0:
            raise ApiError("ERR_INVALID_STATE", "An open critical incident blocks resumption.")
        event["status"] = "IN_PROGRESS"
        event["ingress_status"] = "NORMAL"
        engine.release_held_lanes(event)

    else:  # CLOSE
        _require_status(event, ("IN_PROGRESS",))
        if now() < parse_iso(event["event_end_at"]):
            raise ApiError("ERR_INVALID_STATE", "The logical clock has not reached event_end_at.")
        engine.close_event_cascade(event)
        return object_response(serial.event(event))

    engine.recompute_event(event)
    touch(event)
    return object_response(serial.event(event))


def _check_exit_posts(plan):
    if plan is None:
        raise ApiError("ERR_EXIT_POSTS_UNSTAFFED")
    for post in engine.plan_posts(plan["id"]):
        if post.get("post_type") != "EMERGENCY_EXIT":
            continue
        required = post.get("required_guard_count") or 0
        if (post.get("filled_guard_count") or 0) < required:
            raise ApiError("ERR_EXIT_POSTS_UNSTAFFED")
        on_post = 0
        for assignment in engine.post_assignments(post["id"]):
            if (
                assignment.get("assignment_status") in engine.COMMITTED
                and assignment.get("duty_status") == "ON_POST"
            ):
                on_post += 1
        if on_post < required:
            raise ApiError("ERR_EXIT_POSTS_UNSTAFFED")


def _check_screening_capacity(event, plan):
    required = 0
    if plan is not None:
        assessment = db.assessments.get(plan.get("risk_assessment_id"))
        if assessment is not None and assessment.get("required_screening_lanes") is not None:
            required = assessment["required_screening_lanes"]
    open_lanes = sum(
        1 for lane in engine.event_lanes(event["id"]) if lane.get("status") == "OPEN"
    )
    if open_lanes < required:
        raise ApiError("ERR_SCREENING_CAPACITY_INSUFFICIENT")
