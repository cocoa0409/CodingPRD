"""Agents, evaluators, the quality summary and recognition (PRD 3.2, 3.8, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import calc
import shape
from authz import endpoint
from common import (body, created, fail, new_row, ok, ok_list, require, rows,
                    sorted_rows, touch)
from listing import page
from serial import view, views

bp = Blueprint("people", __name__)

COACHING_STATES = ("NONE", "REQUIRED", "ACTIVE", "CLEARED")
CALIBRATION_STATUSES = ("CALIBRATED", "PROBATION", "SUSPENDED")
ALL_ROLES = ("QualityManager", "QualityEvaluator", "Agent", "Supervisor",
             "ComplianceAuditor")
EVALUATOR_READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor",
                        "ComplianceAuditor")


# --- agents ---------------------------------------------------------------

@bp.post("/agents")
@endpoint("QualityManager")
def create_agent():
    payload = body()
    external_ref = shape.want_string(payload, "external_ref")
    full_name = shape.want_string(payload, "full_name")
    team_code = shape.want_string(payload, "team_code")
    hire_date, _parsed = shape.want_datetime(payload, "hire_date")
    for agent in rows("agents"):
        if agent["external_ref"] == external_ref:
            shape.bad("external_ref must be unique across agents")
    agent = new_row("agents", {
        "external_ref": external_ref,
        "full_name": full_name,
        "team_code": team_code,
        "hire_date": hire_date,
        "quality_index_rolling": None,
        "quality_index_period": None,
        "open_compliance_findings": 0,
        "consecutive_passing_evaluations": 0,
        "coaching_state": "NONE",
        "recognition_points": 0,
    })
    return created(view(agent))


@bp.get("/agents/<agent_id>")
@endpoint(*ALL_ROLES)
def read_agent(agent_id):
    return ok(view(require("agents", agent_id, "ERR_AGENT_NOT_FOUND")))


@bp.get("/agents")
@endpoint("QualityManager", "Supervisor")
def list_agents():
    limit, offset = shape.pagination()
    team_code = shape.query_str("team_code")
    coaching_state = shape.query_enum("coaching_state", COACHING_STATES)
    items = sorted_rows(rows("agents"))
    if team_code is not None:
        items = [a for a in items if a["team_code"] == team_code]
    if coaching_state is not None:
        items = [a for a in items if a["coaching_state"] == coaching_state]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)


@bp.get("/agents/<agent_id>/quality-summary")
@endpoint("QualityManager", "Supervisor", "ComplianceAuditor")
def agent_quality_summary(agent_id):
    agent = require("agents", agent_id, "ERR_AGENT_NOT_FOUND")
    correlation = calc.agent_quality_correlation(agent["id"])
    return ok({
        "quality_index_rolling": calc.quality_index_rolling(agent["id"]),
        "quality_index_period": calc.quality_index_period(agent["id"]),
        "csat_gap_paired": correlation["csat_gap_paired"],
        "csat_gap_all": correlation["csat_gap_all"],
        "repeat_contact_rate": correlation["repeat_contact_rate"],
        "paired_sample_size": correlation["paired_sample_size"],
        "evaluations_considered": correlation["evaluations_considered"],
    })


@bp.post("/agents/<agent_id>/recognition")
@endpoint("QualityManager")
def award_recognition(agent_id):
    payload = body()
    shape.want_string(payload, "award_code")
    points = shape.want_int(payload, "points", minimum=1, maximum=500)
    agent = require("agents", agent_id, "ERR_AGENT_NOT_FOUND")

    if calc.open_compliance_findings(agent["id"]) != 0:
        fail("ERR_COMPLIANCE_HOLD_OPEN",
             "the agent carries an open compliance finding")
    scored = [ev for ev in rows("evaluations")
              if ev["agent_id"] == agent["id"]
              and ev["review_status"] in calc.SCORED_REVIEW_STATUSES]
    if len(scored) < calc.RECOGNITION_MIN_EVALUATIONS:
        fail("ERR_INSUFFICIENT_EVALUATION_HISTORY",
             "the agent needs at least two scored evaluations")
    rolling = agent.get("quality_index_rolling")
    if rolling is None or Decimal(rolling) < calc.RECOGNITION_MIN_INDEX:
        fail("ERR_RECOGNITION_THRESHOLD_NOT_MET",
             "quality_index_rolling must be at least 92.00")

    agent["recognition_points"] = agent["recognition_points"] + points
    touch(agent)
    return ok(view(agent))


# --- evaluators -----------------------------------------------------------

@bp.post("/evaluators")
@endpoint("QualityManager")
def create_evaluator():
    payload = body()
    full_name = shape.want_string(payload, "full_name")
    max_open = shape.want_int(payload, "max_open_assignments", required=False,
                              default=calc.DEFAULT_MAX_OPEN_ASSIGNMENTS,
                              minimum=1, maximum=20)
    evaluator = new_row("evaluators", {
        "full_name": full_name,
        "max_open_assignments": max_open,
        "calibration_status": "CALIBRATED",
        "last_deviation_pct": None,
        "open_assignment_count": 0,
    })
    return created(view(evaluator))


@bp.get("/evaluators/<evaluator_id>")
@endpoint(*EVALUATOR_READ_ROLES)
def read_evaluator(evaluator_id):
    return ok(view(require("evaluators", evaluator_id, "ERR_EVALUATOR_NOT_FOUND")))


@bp.get("/evaluators")
@endpoint("QualityManager", "Supervisor")
def list_evaluators():
    limit, offset = shape.pagination()
    status = shape.query_enum("calibration_status", CALIBRATION_STATUSES)
    items = sorted_rows(rows("evaluators"))
    if status is not None:
        items = [e for e in items if e["calibration_status"] == status]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
