"""Adjustment endpoints (PRD §3.4): propose, decide (OCC + segregation of
duties + budget), reverse."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_INCREASE,
    ERR_STALE_PLAN_VERSION,
    ERR_PLAN_INVALID_STATE,
    ERR_FINDING_INVALID_STATE,
    ERR_CROSS_STUDY_REFERENCE,
    ERR_EFFECTIVE_DATE_IN_PAST,
    ERR_ADJUSTMENT_INVALID_STATE,
    ERR_PLAN_NOT_APPROVED,
    ERR_SELF_DECISION_FORBIDDEN,
    ERR_BUDGET_EXCEEDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import (
    new_record, touch, recompute_plan, check_plan_transitions,
    check_finding_resolution,
)
from util import parse_date, clock_today
from validate import get_body, req_date, require_path_resource, require_fk

bp = Blueprint("adjustments", __name__)


@bp.post("/adjustments")
def create_adjustment():
    caller = authorized(["CompAnalyst"])
    body = get_body()
    plan_id = body.get("plan_id")
    finding_id = body.get("gap_finding_id")
    snapshot_id = body.get("employee_snapshot_id")
    for field, val in (("plan_id", plan_id), ("gap_finding_id", finding_id),
                       ("employee_snapshot_id", snapshot_id)):
        if val is None or not isinstance(val, str) or val.strip() == "":
            raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    # Priority 3: body FK existence, left-to-right
    plan = require_fk("remediation_plans", plan_id, "plan_id")
    finding = require_fk("gap_findings", finding_id, "gap_finding_id")
    snapshot = require_fk("employee_snapshots", snapshot_id, "employee_snapshot_id")
    # Priority 3.7: shape
    pic = body.get("proposed_increase_cents")
    if pic is None or isinstance(pic, bool) or not isinstance(pic, int):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: proposed_increase_cents")
    if pic <= 0:
        raise_error(ERR_INVALID_INCREASE, "proposed_increase_cents must be > 0")
    effective_date = req_date(body, "effective_date")
    # Priority 4: state — plan DRAFT or EXECUTING; finding TARGETED
    if plan["status"] not in ("DRAFT", "EXECUTING"):
        raise_error(ERR_PLAN_INVALID_STATE,
                    "adjustment creation requires the plan to be DRAFT or EXECUTING")
    if finding["status"] != "TARGETED":
        raise_error(ERR_FINDING_INVALID_STATE,
                    "adjustment creation requires a TARGETED finding")
    # Priority 6: temporal — effective_date not before the current clock date
    # (a date equal to the clock date is acceptable)
    if parse_date(effective_date) < clock_today():
        raise_error(ERR_EFFECTIVE_DATE_IN_PAST,
                    "effective_date is before the current logical-clock date")
    # Priority 7: referential consistency — finding and snapshot in the plan's study
    if finding["study_id"] != plan["study_id"] or snapshot["study_id"] != plan["study_id"]:
        raise_error(ERR_CROSS_STUDY_REFERENCE,
                    "finding and snapshot must belong to the plan's study")

    rec = new_record("adjustments", {
        "plan_id": plan_id,
        "gap_finding_id": finding_id,
        "employee_snapshot_id": snapshot_id,
        "study_id": plan["study_id"],
        "proposed_increase_cents": pic,
        "approved_increase_cents": None,
        "effective_date": effective_date,
        "status": "PROPOSED",
        "created_by_user_id": caller.user_id,
        "decided_by_user_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/adjustments")
def list_adjustments():
    return list_response("adjustments", {
        "plan_id": request.args.get("plan_id"),
        "employee_snapshot_id": request.args.get("employee_snapshot_id"),
        "gap_finding_id": request.args.get("gap_finding_id"),
        "study_id": request.args.get("study_id"),
        "status": request.args.get("status"),
    })


@bp.get("/adjustments/<rid>")
def get_adjustment(rid):
    return get_one("adjustments", rid)


@bp.post("/adjustments/<rid>/decision")
def decide_adjustment(rid):
    caller = authorized(["RemediationApprover"])
    # Priority 3: path existence
    adjustment = require_path_resource("adjustments", rid)
    plan = db["remediation_plans"].get(adjustment["plan_id"])
    body = get_body()
    # Priority 3.5: OCC — evaluated BEFORE any state check (PRD §2.6)
    if "expected_plan_version" not in body or body["expected_plan_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: expected_plan_version")
    epv = body["expected_plan_version"]
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise_error(ERR_INVALID_REQUEST, "expected_plan_version must be an integer")
    if plan is None or epv != plan["version"]:
        raise_error(ERR_STALE_PLAN_VERSION,
                    "expected_plan_version does not match the plan's current version")
    # Priority 3.7: shape
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_error(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")
    # Priority 4: state
    if adjustment["status"] != "PROPOSED":
        raise_error(ERR_ADJUSTMENT_INVALID_STATE, "decision requires a PROPOSED adjustment")
    if plan["status"] not in ("APPROVED", "EXECUTING"):
        raise_error(ERR_PLAN_NOT_APPROVED,
                    "adjustment decision requires the plan to be APPROVED or EXECUTING")
    # Priority 5: segregation of duties — decider != proposer
    if caller.user_id == adjustment["created_by_user_id"]:
        raise_error(ERR_SELF_DECISION_FORBIDDEN,
                    "the decider must differ from the adjustment's proposer")

    if decision == "APPROVE":
        # Priority 9: budget check runs last (equality permitted)
        if plan["committed_cents"] + adjustment["proposed_increase_cents"] > plan["total_budget_cents"]:
            raise_error(ERR_BUDGET_EXCEEDED,
                        "committed_cents + proposed_increase_cents exceeds total_budget_cents")
        adjustment["approved_increase_cents"] = adjustment["proposed_increase_cents"]
        adjustment["decided_by_user_id"] = caller.user_id
        adjustment["status"] = "APPROVED"
        touch(adjustment)
        # First approval moves the plan APPROVED -> EXECUTING
        if plan["status"] == "APPROVED":
            plan["status"] = "EXECUTING"
        recompute_plan(plan["id"])           # committed recompute; plan.version += 1
        check_plan_transitions(plan["id"])   # EXECUTING -> FULLY_COMMITTED at exact budget
    else:
        adjustment["decided_by_user_id"] = caller.user_id
        adjustment["status"] = "REJECTED"
        touch(adjustment)
        touch(plan)                          # plan.version += 1
        # GapFinding resolution re-check for the referenced finding
        check_finding_resolution(adjustment["gap_finding_id"])
        check_plan_transitions(plan["id"])
    return success_object(public(adjustment))


@bp.post("/adjustments/<rid>/reverse")
def reverse_adjustment(rid):
    authorized(["RemediationApprover"])
    adjustment = require_path_resource("adjustments", rid)
    body = get_body()
    rationale = body.get("rationale")
    if rationale is None or not isinstance(rationale, str) or rationale.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "rationale is required for reverse")
    plan = db["remediation_plans"].get(adjustment["plan_id"])
    # Priority 4: state
    if adjustment["status"] != "EFFECTIVE":
        raise_error(ERR_ADJUSTMENT_INVALID_STATE, "reverse requires an EFFECTIVE adjustment")
    if plan is None or plan["status"] not in ("EXECUTING", "FULLY_COMMITTED"):
        raise_error(ERR_PLAN_INVALID_STATE,
                    "reverse requires the plan to be EXECUTING or FULLY_COMMITTED")

    adjustment["status"] = "REVERSED"
    touch(adjustment)
    # committed drops by approved_increase_cents; plan.version += 1
    recompute_plan(plan["id"])
    # FULLY_COMMITTED -> EXECUTING when committed falls below the budget
    if plan["status"] == "FULLY_COMMITTED" and plan["committed_cents"] < plan["total_budget_cents"]:
        plan["status"] = "EXECUTING"
        touch(plan)
    # Finding resolution re-check (changes nothing by design, PRD §3.4)
    check_finding_resolution(adjustment["gap_finding_id"])
    check_plan_transitions(plan["id"])
    return success_object(public(adjustment))
