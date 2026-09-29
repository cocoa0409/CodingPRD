"""StaffingPlan endpoints (PRD 3.4)."""

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate, check_action_authority, require_action
from db import db, make_record, sorted_records, touch
from errors import ApiError
from response import object_response
from routes._common import get_assessment, get_event, get_plan, match_filters, paginated

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("DRAFT", "PUBLISHED", "ACTIVATED", "LOCKED", "CLOSED", "SUPERSEDED")
READ_ROLES = {"SecurityDirector", "StaffingCoordinator", "RiskAnalyst", "IncidentCommander"}
COVERAGE_ROLES = {"SecurityDirector", "StaffingCoordinator", "RiskAnalyst"}
LIFECYCLE_ROLES = {"StaffingCoordinator", "SecurityDirector"}


@bp.post("/security-events/<event_id>/staffing-plans")
def create_plan(event_id):
    authenticate({"StaffingCoordinator"})
    payload = valid.body()
    risk_assessment_id = valid.req_string(payload, "risk_assessment_id")
    budget_cents = valid.req_int(payload, "budget_cents", minimum=1)
    expected_version = valid.req_int(payload, "expected_event_version")

    event = get_event(event_id)
    assessment = get_assessment(risk_assessment_id)
    if assessment.get("event_id") != event["id"]:
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH",
            "The referenced risk assessment belongs to a different event.",
        )
    if expected_version != event.get("version"):
        raise ApiError("ERR_STALE_EVENT_VERSION")

    prior = None
    for candidate in sorted_records(list(db.plans.values())):
        if candidate.get("event_id") == event["id"] and candidate.get("status") in (
            "DRAFT",
            "PUBLISHED",
        ):
            prior = candidate

    record = make_record(
        {
            "event_id": event["id"],
            "risk_assessment_id": assessment["id"],
            "pinned_risk_assessment_version": None,
            "supersedes_plan_id": prior["id"] if prior is not None else None,
            "budget_cents": budget_cents,
            "committed_cost_cents": 0,
            "billed_cost_cents": 0,
            "budget_remaining_cents": budget_cents,
            "committed_guard_hours": 0,
            "required_total_staff": 0,
            "filled_total_staff": 0,
            "coverage_ratio": 0,
            "understaffed_post_count": 0,
            "readiness_posture": "BLOCKED",
            "status": "DRAFT",
            "is_current": True,
        }
    )
    db.plans[record["id"]] = record

    if prior is not None:
        engine.supersede_plan(prior)
    else:
        engine.cascade_event_only(event)
    return object_response(serial.plan(record), 201)


@bp.get("/staffing-plans/<plan_id>")
def read_plan(plan_id):
    authenticate(READ_ROLES)
    plan = get_plan(plan_id)
    return object_response(serial.plan(plan))


@bp.get("/staffing-plans")
def list_plans():
    authenticate(READ_ROLES)
    filters = {
        "event_id": valid.query_string("event_id"),
        "risk_assessment_id": valid.query_string("risk_assessment_id"),
        "supersedes_plan_id": valid.query_string("supersedes_plan_id"),
        "status": valid.query_enum("status", PLAN_STATUSES),
        "is_current": valid.query_bool("is_current"),
    }
    records = [p for p in db.plans.values() if match_filters(p, filters)]
    return paginated(records, serial.plan)


@bp.get("/staffing-plans/<plan_id>/coverage-summary")
def coverage_summary(plan_id):
    authenticate(COVERAGE_ROLES)
    plan = get_plan(plan_id)
    data = {
        "required_total_staff": plan.get("required_total_staff"),
        "filled_total_staff": plan.get("filled_total_staff"),
        "coverage_ratio": plan.get("coverage_ratio"),
        "understaffed_post_count": plan.get("understaffed_post_count"),
        "readiness_posture": plan.get("readiness_posture"),
        "committed_cost_cents": plan.get("committed_cost_cents"),
        "budget_remaining_cents": plan.get("budget_remaining_cents"),
        "committed_guard_hours": plan.get("committed_guard_hours"),
        "supervisor_coverage_ok": engine._supervisor_coverage_ok(plan),
    }
    return object_response(data)


@bp.post("/staffing-plans/<plan_id>/lifecycle")
def plan_lifecycle(plan_id):
    actor = authenticate(LIFECYCLE_ROLES)
    payload = valid.body()
    action = require_action(payload, "plan_lifecycle")
    check_action_authority(actor, "plan_lifecycle", action)

    plan = get_plan(plan_id)
    event = db.events.get(plan.get("event_id"))

    if not plan.get("is_current"):
        raise ApiError("ERR_PLAN_NOT_CURRENT")

    def gate():
        if event is not None and event.get("gate_posture") == "FROZEN":
            raise ApiError("ERR_EVENT_GATE_FROZEN")

    def open_posts():
        return [p for p in engine.plan_posts(plan["id"]) if p.get("status") != "CLOSED"]

    if action == "PUBLISH":
        if plan["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Only a DRAFT plan may be published.")
        gate()
        assessment = db.assessments.get(plan.get("risk_assessment_id"))
        if assessment is None or assessment.get("status") != "APPROVED":
            raise ApiError("ERR_ASSESSMENT_NOT_APPROVED")
        if not open_posts():
            raise ApiError("ERR_PLAN_HAS_NO_POSTS")
        if (plan.get("required_total_staff") or 0) < (assessment.get("required_total_staff") or 0):
            raise ApiError("ERR_STAFFING_BELOW_ASSESSED_REQUIREMENT")
        if (plan.get("budget_cents") or 0) < (
            assessment.get("minimum_staffing_cost_floor_cents") or 0
        ):
            raise ApiError("ERR_PLAN_BUDGET_BELOW_FLOOR")
        plan["status"] = "PUBLISHED"
        plan["pinned_risk_assessment_version"] = assessment.get("version")
        engine.recompute_plan(plan)
        touch(plan)
        engine.cascade_event_only(event)

    elif action == "RECALL":
        if plan["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE", "Only a PUBLISHED plan may be recalled.")
        gate()
        for assignment in engine.plan_committed_rows(plan["id"]):
            if assignment.get("assignment_status") == "CONFIRMED":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "A plan with confirmed assignments may not be recalled.",
                )
        plan["status"] = "DRAFT"
        plan["pinned_risk_assessment_version"] = None
        engine.recompute_plan(plan)
        touch(plan)
        engine.cascade_event_only(event)

    elif action == "ACTIVATE":
        if plan["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE", "Only a PUBLISHED plan may be activated.")
        gate()
        if not open_posts():
            raise ApiError("ERR_PLAN_HAS_NO_POSTS")
        if event is None or event.get("status") != "RISK_ASSESSED":
            raise ApiError("ERR_INVALID_STATE", "The event is not in RISK_ASSESSED.")
        plan["status"] = "ACTIVATED"
        for post in engine.plan_posts(plan["id"]):
            if engine.recompute_post(post, plan):
                touch(post)
        engine.recompute_plan(plan)
        touch(plan)
        event["status"] = "STAFFED"
        engine.recompute_event(event)
        touch(event)

    elif action == "LOCK":
        if plan["status"] != "ACTIVATED":
            raise ApiError("ERR_INVALID_STATE", "Only an ACTIVATED plan may be locked.")
        if event is None or event.get("status") not in (
            "BRIEFED",
            "DOORS_OPEN",
            "IN_PROGRESS",
            "SUSPENDED",
        ):
            raise ApiError("ERR_INVALID_STATE", "The event is not live.")
        plan["status"] = "LOCKED"
        engine.recompute_plan(plan)
        touch(plan)
        engine.cascade_event_only(event)

    else:  # CLOSE
        if plan["status"] != "LOCKED":
            raise ApiError("ERR_INVALID_STATE", "Only a LOCKED plan may be closed.")
        plan["status"] = "CLOSED"
        for post in engine.plan_posts(plan["id"]):
            if engine.recompute_post(post, plan):
                touch(post)
        engine.recompute_plan(plan)
        touch(plan)
        engine.cascade_event_only(event)

    return object_response(serial.plan(plan))
