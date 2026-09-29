"""PostAssignment endpoints: rostering and the duty-event dimension (PRD 3.6, 3.7)."""

from datetime import timedelta

from flask import Blueprint

import engine
import serial
import valid
from auth import (
    acting_guard,
    authenticate,
    check_action_authority,
    check_supervisor_standing,
    require_action,
)
from db import clock_iso, db, make_record, now, now_iso, parse_iso, touch
from errors import ApiError
from response import object_response
from routes._common import get_assignment, match_filters, paginated

bp = Blueprint("assignments", __name__)

ASSIGNMENT_STATUSES = ("TENTATIVE", "CONFIRMED", "CANCELLED", "VOIDED", "COMPLETED")
DUTY_STATUSES = ("PENDING_BRIEF", "BRIEFED", "ON_POST", "NO_SHOW", "RELIEVED")
READ_ROLES = {"SecurityDirector", "StaffingCoordinator", "IncidentCommander", "PostSupervisor"}
SUPERVISOR_MIN_CREDENTIAL_LEVEL = 3
CHECK_IN_LEAD_MIN = 30
NO_SHOW_GRACE_MIN = 15


@bp.post("/post-assignments")
def create_assignment():
    authenticate({"StaffingCoordinator"})
    payload = valid.body()
    post_id = valid.req_string(payload, "post_id")
    guard_id = valid.req_string(payload, "guard_id")
    window_start = valid.req_datetime(payload, "window_start")
    window_end = valid.req_datetime(payload, "window_end")
    if window_end[1] <= window_start[1]:
        valid.bad("Field 'window_end' must be strictly after 'window_start'.")

    post = db.posts.get(post_id)
    if post is None:
        raise ApiError("ERR_POST_NOT_FOUND")
    guard = db.guards.get(guard_id)
    if guard is None:
        raise ApiError("ERR_GUARD_NOT_FOUND")

    plan = db.plans.get(post.get("staffing_plan_id"))
    event = db.events.get(plan.get("event_id")) if plan else None

    if plan is not None and plan.get("status") == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED")
    if plan is not None and not plan.get("is_current"):
        raise ApiError("ERR_PLAN_NOT_CURRENT")
    if event is not None and event.get("gate_posture") == "FROZEN":
        raise ApiError("ERR_EVENT_GATE_FROZEN")

    post_start = parse_iso(post["window_start"])
    post_end = parse_iso(post["window_end"])
    if window_start[1] < post_start or window_end[1] > post_end:
        raise ApiError("ERR_ASSIGNMENT_WINDOW_OUTSIDE_POST")

    record = make_record(
        {
            "post_id": post["id"],
            "guard_id": guard["id"],
            "window_start": window_start[0],
            "window_end": window_end[0],
            "assignment_status": "TENTATIVE",
            "duty_status": "PENDING_BRIEF",
            "billed_hours": None,
            "billed_cost_cents": None,
            "radio_channel": None,
            "training_module_code": None,
            "briefed_at": None,
            "check_in_at": None,
            "relieved_at": None,
            "cancellation_reason": None,
        }
    )
    engine.price_assignment(record, guard)
    db.assignments[record["id"]] = record
    return object_response(serial.assignment(record), 201)


@bp.get("/post-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate(READ_ROLES)
    assignment = get_assignment(assignment_id)
    return object_response(serial.assignment(assignment))


@bp.get("/post-assignments")
def list_assignments():
    authenticate(READ_ROLES)
    filters = {
        "post_id": valid.query_string("post_id"),
        "guard_id": valid.query_string("guard_id"),
        "assignment_status": valid.query_enum("assignment_status", ASSIGNMENT_STATUSES),
        "duty_status": valid.query_enum("duty_status", DUTY_STATUSES),
    }
    records = [a for a in db.assignments.values() if match_filters(a, filters)]
    return paginated(records, serial.assignment)


def _bad_state(message):
    raise ApiError("ERR_INVALID_STATE", message)


@bp.post("/post-assignments/<assignment_id>/duty-events")
def duty_events(assignment_id):
    actor = authenticate({"StaffingCoordinator", "PostSupervisor"})
    payload = valid.body()
    action = require_action(payload, "duty_events")
    check_action_authority(actor, "duty_events", action)

    if actor.is_supervisor:
        acting_guard(actor)

    assignment = get_assignment(assignment_id)
    post = db.posts.get(assignment.get("post_id"))
    plan = db.plans.get(post.get("staffing_plan_id")) if post else None
    event = db.events.get(plan.get("event_id")) if plan else None
    guard = db.guards.get(assignment.get("guard_id"))

    if actor.is_supervisor:
        check_supervisor_standing(actor, assignment, post, plan)

    radio_channel = None
    training_module_code = None
    cancellation_reason = None
    if action == "BRIEF":
        radio_channel = valid.req_string(payload, "radio_channel")
        training_module_code = valid.req_string(payload, "training_module_code")
    elif action == "CANCEL":
        cancellation_reason = valid.opt_string(payload, "cancellation_reason")

    if action in ("CONFIRM", "CANCEL") and plan is not None and plan.get("status") == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED")
    if plan is not None and not plan.get("is_current"):
        raise ApiError("ERR_PLAN_NOT_CURRENT")

    roster = assignment.get("assignment_status")
    duty = assignment.get("duty_status")

    if action == "CONFIRM":
        if roster != "TENTATIVE":
            _bad_state("Only a TENTATIVE assignment may be confirmed.")
        if plan is None or plan.get("status") not in ("PUBLISHED", "ACTIVATED"):
            _bad_state("The plan is not open for confirmations.")
        if event is not None and event.get("gate_posture") == "FROZEN":
            raise ApiError("ERR_EVENT_GATE_FROZEN")
        window_end = parse_iso(assignment["window_end"])
        credential_expiry = parse_iso(guard.get("credential_expires_on")) if guard else None
        if (
            guard is None
            or guard.get("verification_status") != "VERIFIED"
            or credential_expiry is None
            or credential_expiry <= window_end
        ):
            raise ApiError("ERR_GUARD_CREDENTIAL_INVALID")
        if guard.get("credential_level") < (post.get("min_credential_level") or 0):
            raise ApiError("ERR_CREDENTIAL_LEVEL_INSUFFICIENT")
        if (
            post.get("post_type") == "SUPERVISOR"
            and guard.get("credential_level") < SUPERVISOR_MIN_CREDENTIAL_LEVEL
        ):
            raise ApiError("ERR_SUPERVISOR_NOT_QUALIFIED")
        if guard.get("employment_type") == "SUBCONTRACTED":
            vendor = db.subcontractors.get(guard.get("subcontractor_id"))
            vendor_expiry = parse_iso(vendor.get("insurance_expires_on")) if vendor else None
            if (
                vendor is None
                or vendor.get("status") != "APPROVED"
                or vendor_expiry is None
                or vendor_expiry <= window_end
            ):
                raise ApiError("ERR_SUBCONTRACTOR_NOT_ELIGIBLE")
        window_start = parse_iso(assignment["window_start"])
        for other in db.assignments.values():
            if other["id"] == assignment["id"]:
                continue
            if other.get("guard_id") != assignment.get("guard_id"):
                continue
            if other.get("assignment_status") not in ("TENTATIVE", "CONFIRMED"):
                continue
            other_start = parse_iso(other["window_start"])
            other_end = parse_iso(other["window_end"])
            if other_start < window_end and window_start < other_end:
                raise ApiError("ERR_GUARD_WINDOW_CONFLICT")
        if engine.post_filled_count(post["id"]) >= (post.get("required_guard_count") or 0):
            raise ApiError("ERR_POST_FULLY_STAFFED")
        if (assignment.get("line_cost_cents") or 0) > (plan.get("budget_remaining_cents") or 0):
            raise ApiError("ERR_PLAN_BUDGET_EXCEEDED")

        assignment["assignment_status"] = "CONFIRMED"
        touch(assignment)
        engine.cascade_up([post])

    elif action == "CANCEL":
        if roster not in ("TENTATIVE", "CONFIRMED"):
            _bad_state("Only a TENTATIVE or CONFIRMED assignment may be cancelled.")
        if roster == "CONFIRMED" and duty not in ("PENDING_BRIEF", "BRIEFED"):
            _bad_state("A guard already on post may not be cancelled off the roster.")
        if event is not None and event.get("gate_posture") == "FROZEN":
            raise ApiError("ERR_EVENT_GATE_FROZEN")
        assignment["assignment_status"] = "CANCELLED"
        assignment["cancellation_reason"] = cancellation_reason
        touch(assignment)
        engine.cascade_up([post])

    elif action == "BRIEF":
        if roster != "CONFIRMED":
            _bad_state("Only a CONFIRMED assignment may be briefed.")
        if duty != "PENDING_BRIEF":
            _bad_state("Only a PENDING_BRIEF assignment may be briefed.")
        if event is None or event.get("status") not in ("STAFFED", "BRIEFED"):
            _bad_state("The event is not in a briefing state.")
        assignment["duty_status"] = "BRIEFED"
        assignment["radio_channel"] = radio_channel
        assignment["training_module_code"] = training_module_code
        assignment["briefed_at"] = clock_iso()
        touch(assignment)

    elif action == "CHECK_IN":
        if roster != "CONFIRMED":
            _bad_state("Only a CONFIRMED assignment may check in.")
        if duty == "PENDING_BRIEF":
            raise ApiError("ERR_GUARD_NOT_BRIEFED")
        if duty != "BRIEFED":
            _bad_state("Only a BRIEFED assignment may check in.")
        if event is None or event.get("status") not in (
            "BRIEFED",
            "DOORS_OPEN",
            "IN_PROGRESS",
            "SUSPENDED",
        ):
            _bad_state("The event is not live.")
        window_start = parse_iso(assignment["window_start"])
        if now() < window_start - timedelta(minutes=CHECK_IN_LEAD_MIN):
            _bad_state("Check-in is not yet open for this shift.")
        assignment["duty_status"] = "ON_POST"
        assignment["check_in_at"] = clock_iso()
        touch(assignment)
        engine.refresh_lane_for_post(post)

    elif action == "MARK_NO_SHOW":
        if roster != "CONFIRMED":
            _bad_state("Only a CONFIRMED assignment may be marked as a no-show.")
        if duty not in ("PENDING_BRIEF", "BRIEFED"):
            _bad_state("This assignment may not be marked as a no-show.")
        window_start = parse_iso(assignment["window_start"])
        if now() < window_start + timedelta(minutes=NO_SHOW_GRACE_MIN):
            _bad_state("The no-show grace period has not elapsed.")
        assignment["duty_status"] = "NO_SHOW"
        touch(assignment)
        engine.cascade_up([post])

    else:  # RELIEVE
        if roster != "CONFIRMED":
            _bad_state("Only a CONFIRMED assignment may be relieved.")
        if duty != "ON_POST":
            _bad_state("Only an ON_POST assignment may be relieved.")
        if assignment.get("check_in_at") is None:
            _bad_state("This assignment has no check-in to relieve.")
        assignment["duty_status"] = "RELIEVED"
        assignment["relieved_at"] = clock_iso()
        if guard is not None:
            engine.price_billed(assignment, guard)
        assignment["assignment_status"] = "COMPLETED"
        touch(assignment)
        engine.refresh_lane_for_post(post)
        engine.cascade_up([post])

    return object_response(serial.assignment(assignment))
