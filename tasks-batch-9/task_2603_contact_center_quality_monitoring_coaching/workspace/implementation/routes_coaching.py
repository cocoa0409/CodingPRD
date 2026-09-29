"""Coaching plans: intervention, escalation and completion (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import calc
import derive
import shape
from common import (body, clock_now, created, fail, fmt_dt, get, new_row, ok,
                    ok_list, parse_dt, require, rows, sorted_rows, touch)
from authz import endpoint
from listing import page
from serial import view, views

bp = Blueprint("coaching", __name__)

PLAN_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "ESCALATED", "VOIDED")
TIERS = ("T1", "T2", "T3")
LIVE = ("ASSIGNED", "IN_PROGRESS")
TERMINAL = ("COMPLETED", "ESCALATED", "VOIDED")
READ_ROLES = ("QualityManager", "Supervisor", "ComplianceAuditor", "Agent")
LIST_ROLES = ("QualityManager", "Supervisor", "ComplianceAuditor")


@bp.post("/coaching-plans")
@endpoint("Supervisor")
def create_plan():
    payload = body()
    agent_id = shape.want_string(payload, "agent_id")
    evaluation_id = shape.want_string(payload, "source_evaluation_id")
    supervisor_id = shape.want_string(payload, "assigned_supervisor_id")
    target = shape.want_decimal(payload, "target_score",
                                exclusive_min=Decimal("0.00"),
                                maximum=Decimal("100.00"))
    expected = shape.want_int(payload, "expected_agent_version", minimum=0)

    agent = require("agents", agent_id, "ERR_AGENT_NOT_FOUND")
    evaluation = require("evaluations", evaluation_id, "ERR_EVALUATION_NOT_FOUND")

    if expected != agent["version"]:
        fail("ERR_STALE_AGENT_VERSION",
             "expected_agent_version does not match the agent's version")

    if evaluation["agent_id"] != agent["id"]:
        shape.bad("the source evaluation does not belong to the named agent")

    if agent["quality_index_rolling"] is None:
        fail("ERR_INSUFFICIENT_EVALUATION_HISTORY",
             "the agent has no scored evaluation to size a plan from")

    sizing = calc.coaching_requirement(target, agent["quality_index_rolling"],
                                       agent["open_compliance_findings"])
    if sizing is None:
        shape.bad("target_score leaves no positive deficit to close")

    plan = new_row("coaching_plans", {
        "agent_id": agent["id"],
        "source_evaluation_id": evaluation["id"],
        "assigned_supervisor_id": supervisor_id,
        "target_score": target,
        "deficit_pct": sizing["deficit_pct"],
        "escalation_tier": sizing["escalation_tier"],
        "required_session_count": sizing["required_session_count"],
        "completed_session_count": 0,
        "due_at": fmt_dt(sizing["due_at"]),
        "status": "ASSIGNED",
        "escalation_note": None,
    })

    for other in sorted_rows(rows("coaching_plans")):
        if (other["id"] != plan["id"] and other["agent_id"] == agent["id"]
                and other["status"] in LIVE):
            other["status"] = "VOIDED"
            touch(other)

    derive.force(agent, {"coaching_state": "ACTIVE"})
    return created(view(plan))


@bp.post("/coaching-plans/<plan_id>/log-session")
@endpoint("Supervisor")
def log_session(plan_id):
    payload = body()
    shape.want_string(payload, "session_note")
    session_raw, session_at = shape.want_datetime(payload, "session_at")

    plan = require("coaching_plans", plan_id, "ERR_COACHING_PLAN_NOT_FOUND")
    if session_at < parse_dt(plan["created_at"]):
        shape.bad("session_at may not be earlier than the plan's created_at")
    if plan["status"] not in LIVE:
        fail("ERR_COACHING_PLAN_TERMINAL", "this coaching plan is no longer active")

    plan["status"] = "IN_PROGRESS"
    plan["completed_session_count"] = int(plan["completed_session_count"]) + 1
    touch(plan)
    return ok(view(plan))


@bp.post("/coaching-plans/<plan_id>/complete")
@endpoint("Supervisor")
def complete_plan(plan_id):
    plan = require("coaching_plans", plan_id, "ERR_COACHING_PLAN_NOT_FOUND")
    if plan["status"] in TERMINAL:
        fail("ERR_COACHING_PLAN_TERMINAL", "this coaching plan is no longer active")

    agent = get("agents", plan["agent_id"])
    findings = calc.open_compliance_findings(plan["agent_id"])
    if findings != 0:
        fail("ERR_COMPLIANCE_HOLD_OPEN",
             "a coaching plan may not be signed off while a compliance finding stands")
    if int(plan["completed_session_count"]) < int(plan["required_session_count"]):
        fail("ERR_SESSIONS_INCOMPLETE",
             "every required coaching session must be logged first")

    plan["status"] = "COMPLETED"
    touch(plan)
    if agent is not None:
        derive.force(agent, {"coaching_state": "CLEARED"})
    return ok(view(plan))


@bp.post("/coaching-plans/<plan_id>/escalate")
@endpoint("QualityManager")
def escalate_plan(plan_id):
    payload = body()
    note = shape.want_string(payload, "escalation_note")

    plan = require("coaching_plans", plan_id, "ERR_COACHING_PLAN_NOT_FOUND")
    if plan["status"] in TERMINAL:
        fail("ERR_COACHING_PLAN_TERMINAL", "this coaching plan is no longer active")

    due = parse_dt(plan["due_at"])
    findings = calc.open_compliance_findings(plan["agent_id"])
    if not (due is not None and clock_now() >= due) and findings < 2:
        fail("ERR_ESCALATION_NOT_DUE",
             "the plan is not yet due and fewer than two findings stand open")

    plan["status"] = "ESCALATED"
    plan["escalation_note"] = note
    plan["escalation_tier"] = "T3"
    touch(plan)
    return ok(view(plan))


@bp.get("/coaching-plans/<plan_id>")
@endpoint(*READ_ROLES)
def read_plan(plan_id):
    return ok(view(require("coaching_plans", plan_id, "ERR_COACHING_PLAN_NOT_FOUND")))


@bp.get("/coaching-plans")
@endpoint(*LIST_ROLES)
def list_plans():
    limit, offset = shape.pagination()
    agent_id = shape.query_str("agent_id")
    evaluation_id = shape.query_str("source_evaluation_id")
    status = shape.query_enum("status", PLAN_STATUSES)
    tier = shape.query_enum("escalation_tier", TIERS)
    items = sorted_rows(rows("coaching_plans"))
    if agent_id is not None:
        items = [p for p in items if p["agent_id"] == agent_id]
    if evaluation_id is not None:
        items = [p for p in items if p["source_evaluation_id"] == evaluation_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if tier is not None:
        items = [p for p in items if p["escalation_tier"] == tier]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
