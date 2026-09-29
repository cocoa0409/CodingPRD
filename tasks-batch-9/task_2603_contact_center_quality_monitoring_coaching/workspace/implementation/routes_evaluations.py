"""Evaluations: scoring, delivery and acknowledgement (PRD 3.5, 3.6)."""
from flask import Blueprint

import calc
import derive
import scoring
import shape
from common import (body, created, fail, get, new_row, now_iso, ok, ok_list,
                    require, rows, sorted_rows, touch)
from authz import actor, endpoint
from listing import page
from serial import view, views

bp = Blueprint("evaluations", __name__)

REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "FINALIZED", "REOPENED")
FEEDBACK_STATUSES = ("PENDING", "DELIVERED", "ACKNOWLEDGED", "DISPUTED")
COMPLIANCE_RESULTS = ("PASS", "FAIL", "NOT_EVALUATED")
AGREEMENTS = ("AGREE", "DISAGREE")
CONSENT_OK = ("VERIFIED", "NOT_REQUIRED")
READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor",
              "ComplianceAuditor", "Agent")
LIST_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor", "ComplianceAuditor")


def consent_gate(interaction):
    if interaction is None or interaction["recording_consent_status"] not in CONSENT_OK:
        fail("ERR_CONSENT_NOT_VERIFIED",
             "the interaction's recording consent is not VERIFIED or NOT_REQUIRED")


@bp.post("/evaluations")
@endpoint("QualityEvaluator")
def create_evaluation():
    payload = body()
    selection_id = shape.want_string(payload, "selection_id")
    selection = require("selections", selection_id, "ERR_SELECTION_NOT_FOUND")

    holder = selection.get("assigned_evaluator_id")
    if holder is not None and holder != actor():
        fail("ERR_NOT_RESOURCE_OWNER",
             "the selection is assigned to another evaluator")
    if selection["status"] != "ASSIGNED":
        fail("ERR_SELECTION_NOT_ASSIGNABLE",
             "an evaluation may only be opened on an ASSIGNED selection")

    consent_gate(get("interactions", selection["interaction_id"]))

    plan = get("plans", selection["plan_id"])
    form = get("forms", plan["form_id"])
    if plan["pinned_form_guidance_version"] != form["guidance_version"]:
        fail("ERR_GUIDANCE_VERSION_STALE",
             "the plan's pinned guidance revision no longer matches the form")

    evaluation = new_row("evaluations", {
        "selection_id": selection["id"],
        "evaluator_id": selection["assigned_evaluator_id"],
        "form_id": plan["form_id"],
        "agent_id": selection["agent_id"],
        "pinned_guidance_version": plan["pinned_form_guidance_version"],
        "item_scores": {},
        "weighted_score": None,
        "raw_weighted_score": None,
        "adjusted_weighted_score": None,
        "auto_fail_triggered": False,
        "compliance_result": "NOT_EVALUATED",
        "review_status": "DRAFT",
        "feedback_status": "PENDING",
        "submitted_at": None,
        "feedback_delivered_at": None,
        "agreement": None,
    })
    return created(view(evaluation))


@bp.post("/evaluations/<evaluation_id>/submit")
@endpoint("QualityEvaluator")
def submit_evaluation(evaluation_id):
    payload = body()
    scores = shape.want_item_scores(payload, "item_scores")

    ev = require("evaluations", evaluation_id, "ERR_EVALUATION_NOT_FOUND")
    if ev["evaluator_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER", "only the scoring evaluator may submit")
    if ev["review_status"] not in ("DRAFT", "REOPENED"):
        fail("ERR_EVALUATION_NOT_EDITABLE",
             "only a DRAFT or REOPENED evaluation may be submitted")

    selection = get("selections", ev["selection_id"])
    interaction = None if selection is None else get("interactions",
                                                    selection["interaction_id"])
    consent_gate(interaction)

    evaluator = get("evaluators", ev["evaluator_id"])
    if evaluator is not None and evaluator["calibration_status"] == "SUSPENDED":
        fail("ERR_EVALUATOR_NOT_CALIBRATED",
             "a SUSPENDED evaluator may not submit a score")

    expected_selection = "ASSIGNED" if ev["review_status"] == "DRAFT" else "EVALUATED"
    if selection is None or selection["status"] != expected_selection:
        fail("ERR_SELECTION_NOT_ASSIGNABLE",
             "the underlying selection must be %s" % expected_selection)

    plan = get("plans", selection["plan_id"])
    form = get("forms", ev["form_id"])
    if plan is None or ev["form_id"] != plan["form_id"]:
        fail("ERR_FORM_VERSION_MISMATCH",
             "the evaluation's form no longer matches its plan's scorecard")
    behaviors = calc.form_behaviors(ev["form_id"])
    scoring.validate_item_scores(behaviors, scores)

    if ev["pinned_guidance_version"] != form["guidance_version"]:
        fail("ERR_GUIDANCE_VERSION_STALE",
             "the pinned guidance revision no longer matches the form")

    result = calc.evaluation_weighted_score(form, behaviors, scores)

    # STEP ONE + TWO -- scores and the review dimension.
    reopened = ev["review_status"] == "REOPENED"
    ev["item_scores"] = dict(scores)
    ev["weighted_score"] = result["weighted_score"]
    ev["raw_weighted_score"] = result["raw_weighted_score"]
    ev["auto_fail_triggered"] = result["auto_fail_triggered"]
    ev["compliance_result"] = result["compliance_result"]
    if reopened:
        ev["adjusted_weighted_score"] = None
    ev["review_status"] = "SUBMITTED"
    ev["submitted_at"] = now_iso()
    touch(ev)

    # STEP THREE -- the selection leaves the assignment pool.
    if selection["status"] == "ASSIGNED":
        selection["status"] = "EVALUATED"
    touch(selection)
    derive.recompute_evaluator(ev["evaluator_id"])

    # STEP FIVE, hop one -- the compliance hold on the interaction.
    hold_moved = False
    if result["compliance_result"] == "FAIL" and not interaction["compliance_hold"]:
        interaction["compliance_hold"] = True
        hold_moved = True
    touch(interaction)

    # STEP FOUR + hop two -- the agent's aggregates, written once.
    agent_id = ev["agent_id"]
    agent = get("agents", agent_id)
    coaching_moved = False
    if agent is not None:
        updates = {
            "quality_index_rolling": calc.quality_index_rolling(agent_id),
            "quality_index_period": calc.quality_index_period(agent_id),
            "consecutive_passing_evaluations":
                calc.consecutive_passing_evaluations(agent_id),
            "open_compliance_findings": calc.open_compliance_findings(agent_id),
        }
        if hold_moved and agent["coaching_state"] in ("NONE", "CLEARED"):
            updates["coaching_state"] = "REQUIRED"
            coaching_moved = True
        derive.force(agent, updates)

    # Hop three -- one extra targeted slot on the reservation-target plan.
    if coaching_moved:
        target = calc.open_plan_for_clock()
        if target is not None:
            reserve = dict(target.get("targeted_reserve_by_agent") or {})
            reserve[agent_id] = int(reserve.get(agent_id, 0)) + 1
            target["targeted_reserve_by_agent"] = reserve
            derive.force(target, calc.sample_quota_attainment(target))

    return ok(view(ev))


@bp.post("/evaluations/<evaluation_id>/deliver")
@endpoint("QualityEvaluator", "Supervisor")
def deliver_evaluation(evaluation_id):
    ev = require("evaluations", evaluation_id, "ERR_EVALUATION_NOT_FOUND")
    if ev["review_status"] not in ("SUBMITTED", "FINALIZED"):
        fail("ERR_EVALUATION_NOT_DELIVERABLE",
             "only a SUBMITTED or FINALIZED evaluation may be delivered")
    if ev["feedback_status"] != "PENDING":
        fail("ERR_FEEDBACK_ALREADY_DELIVERED",
             "this feedback has already been delivered")
    ev["feedback_status"] = "DELIVERED"
    ev["feedback_delivered_at"] = now_iso()
    touch(ev)
    return ok(view(ev))


@bp.post("/evaluations/<evaluation_id>/acknowledge")
@endpoint("Agent")
def acknowledge_evaluation(evaluation_id):
    payload = body()
    agreement = shape.want_enum(payload, "agreement", AGREEMENTS)

    ev = require("evaluations", evaluation_id, "ERR_EVALUATION_NOT_FOUND")
    if ev["agent_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER",
             "only the evaluated agent may acknowledge this feedback")
    if ev["feedback_status"] != "DELIVERED":
        fail("ERR_FEEDBACK_NOT_DELIVERED", "this feedback is not in DELIVERED")

    ev["feedback_status"] = "ACKNOWLEDGED"
    ev["agreement"] = agreement
    if ev["review_status"] == "SUBMITTED":
        ev["review_status"] = "FINALIZED"
    touch(ev)

    agent = get("agents", ev["agent_id"])
    if agent is not None:
        updates = {}
        if calc._passing(ev):
            updates["consecutive_passing_evaluations"] = int(
                agent["consecutive_passing_evaluations"] or 0) + 1
        derive.force(agent, updates)
    return ok(view(ev))


@bp.get("/evaluations/<evaluation_id>")
@endpoint(*READ_ROLES)
def read_evaluation(evaluation_id):
    return ok(view(require("evaluations", evaluation_id, "ERR_EVALUATION_NOT_FOUND")))


@bp.get("/evaluations")
@endpoint(*LIST_ROLES)
def list_evaluations():
    limit, offset = shape.pagination()
    selection_id = shape.query_str("selection_id")
    evaluator_id = shape.query_str("evaluator_id")
    form_id = shape.query_str("form_id")
    agent_id = shape.query_str("agent_id")
    review_status = shape.query_enum("review_status", REVIEW_STATUSES)
    feedback_status = shape.query_enum("feedback_status", FEEDBACK_STATUSES)
    compliance_result = shape.query_enum("compliance_result", COMPLIANCE_RESULTS)
    items = sorted_rows(rows("evaluations"))
    if selection_id is not None:
        items = [e for e in items if e["selection_id"] == selection_id]
    if evaluator_id is not None:
        items = [e for e in items if e["evaluator_id"] == evaluator_id]
    if form_id is not None:
        items = [e for e in items if e["form_id"] == form_id]
    if agent_id is not None:
        items = [e for e in items if e["agent_id"] == agent_id]
    if review_status is not None:
        items = [e for e in items if e["review_status"] == review_status]
    if feedback_status is not None:
        items = [e for e in items if e["feedback_status"] == feedback_status]
    if compliance_result is not None:
        items = [e for e in items if e["compliance_result"] == compliance_result]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
