"""Disputes: the cyclic adjudication machine (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import calc
import derive
import scoring
import shape
from common import (body, clock_now, created, fail, get, new_row, ok, ok_list,
                    parse_dt, require, rows, sorted_rows, touch)
from authz import actor, endpoint
from listing import page
from serial import view, views

bp = Blueprint("disputes", __name__)

DISPUTE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO", "UPHELD",
                    "REJECTED")
OPEN_DISPUTE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO")
OUTCOMES = ("UPHELD", "REJECTED", "NEEDS_MORE_INFO")
READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor",
              "ComplianceAuditor", "Agent")
LIST_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor", "ComplianceAuditor")


def segregation(dispute):
    evaluation = get("evaluations", dispute["evaluation_id"])
    if evaluation is not None and evaluation["evaluator_id"] == actor():
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the evaluator who produced the score may not adjudicate its challenge")
    return evaluation


@bp.post("/disputes")
@endpoint("Agent")
def create_dispute():
    payload = body()
    evaluation_id = shape.want_string(payload, "evaluation_id")
    codes = shape.opt(payload, "disputed_behavior_codes")
    if not isinstance(codes, list) or not codes:
        shape.bad("field 'disputed_behavior_codes' must be a non-empty array")
    for code in codes:
        if not isinstance(code, str):
            shape.bad("field 'disputed_behavior_codes' entries must be strings")
    if len(set(codes)) != len(codes):
        shape.bad("field 'disputed_behavior_codes' may not carry duplicates")
    rationale = shape.want_string(payload, "rationale", min_len=10, max_len=1000)
    expected = shape.want_int(payload, "expected_evaluation_version", minimum=0)

    ev = require("evaluations", evaluation_id, "ERR_EVALUATION_NOT_FOUND")
    if ev["agent_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER", "only the evaluated agent may file a dispute")
    if expected != ev["version"]:
        fail("ERR_STALE_EVALUATION_VERSION",
             "expected_evaluation_version does not match the evaluation's version")
    if ev["feedback_status"] not in ("DELIVERED", "ACKNOWLEDGED", "DISPUTED"):
        fail("ERR_FEEDBACK_NOT_DELIVERED",
             "feedback must have been delivered before it may be disputed")

    known = {b["code"] for b in calc.form_behaviors(ev["form_id"])}
    for code in codes:
        if code not in known:
            shape.bad("'%s' is not a behaviour code of the evaluation's form" % code)

    for other in rows("disputes"):
        if (other["evaluation_id"] == ev["id"]
                and other["status"] in OPEN_DISPUTE_STATUSES):
            fail("ERR_DISPUTE_ALREADY_OPEN",
                 "this evaluation already carries an open dispute")

    delivered = parse_dt(ev.get("feedback_delivered_at"))
    if delivered is None or clock_now() > delivered + timedelta(
            days=calc.DISPUTE_WINDOW_DAYS):
        fail("ERR_DISPUTE_WINDOW_EXPIRED",
             "the seven-day dispute window has closed")

    dispute = new_row("disputes", {
        "evaluation_id": ev["id"],
        "agent_id": ev["agent_id"],
        "reviewer_evaluator_id": None,
        "disputed_behavior_codes": list(codes),
        "rationale": rationale,
        "adjusted_item_scores": None,
        "outcome_note": None,
        "status": "SUBMITTED",
        "round_count": 0,
    })
    ev["feedback_status"] = "DISPUTED"
    touch(ev)
    return created(view(dispute))


@bp.post("/disputes/<dispute_id>/review")
@endpoint("QualityEvaluator")
def review_dispute(dispute_id):
    dispute = require("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    segregation(dispute)
    if dispute["status"] != "SUBMITTED":
        fail("ERR_DISPUTE_NOT_REVIEWABLE", "only a SUBMITTED dispute may be picked up")
    reviewer = get("evaluators", actor())
    if reviewer is not None and reviewer["calibration_status"] == "SUSPENDED":
        fail("ERR_EVALUATOR_NOT_CALIBRATED",
             "a SUSPENDED evaluator may not review a dispute")
    if int(dispute["round_count"]) >= calc.MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUND_LIMIT",
             "this dispute has already used its two review rounds")

    dispute["status"] = "UNDER_REVIEW"
    dispute["reviewer_evaluator_id"] = actor()
    dispute["round_count"] = int(dispute["round_count"]) + 1
    touch(dispute)
    return ok(view(dispute))


def _resolve_needs_more_info(dispute, note, adjusted):
    if adjusted is not None:
        shape.bad("adjusted_item_scores may not accompany a NEEDS_MORE_INFO outcome")
    if int(dispute["round_count"]) >= calc.MAX_DISPUTE_ROUNDS:
        fail("ERR_DISPUTE_ROUND_LIMIT",
             "no further round may be opened on this dispute")
    dispute["status"] = "NEEDS_MORE_INFO"
    dispute["outcome_note"] = note
    touch(dispute)


def _resolve_rejected(dispute, evaluation, note, adjusted):
    if adjusted is not None:
        shape.bad("adjusted_item_scores may not accompany a REJECTED outcome")
    dispute["status"] = "REJECTED"
    dispute["outcome_note"] = note
    touch(dispute)
    evaluation["feedback_status"] = "DELIVERED"
    if evaluation["review_status"] == "SUBMITTED":
        evaluation["review_status"] = "FINALIZED"
    touch(evaluation)


def _resolve_upheld(dispute, evaluation, note, adjusted):
    if adjusted is None:
        fail("ERR_ITEM_SCORE_INCOMPLETE",
             "an upheld dispute requires a full replacement scorecard")
    form = get("forms", evaluation["form_id"])
    behaviors = calc.form_behaviors(evaluation["form_id"])
    scoring.validate_item_scores(behaviors, adjusted)

    stored = evaluation.get("item_scores") or {}
    if not any(adjusted.get(code) != stored.get(code)
               for code in dispute["disputed_behavior_codes"]):
        shape.bad("the adjusted scores must differ on at least one disputed behaviour")

    result = calc.evaluation_weighted_score(form, behaviors, adjusted)

    dispute["status"] = "UPHELD"
    dispute["outcome_note"] = note
    dispute["adjusted_item_scores"] = dict(adjusted)
    touch(dispute)

    # HOP ONE -- the adjusted score reopens the evaluation.
    was_fail = evaluation["compliance_result"] == "FAIL"
    evaluation["adjusted_weighted_score"] = result["weighted_score"]
    evaluation["compliance_result"] = result["compliance_result"]
    evaluation["review_status"] = "REOPENED"
    evaluation["feedback_status"] = "PENDING"
    evaluation["feedback_delivered_at"] = None
    touch(evaluation)

    if not (was_fail and result["compliance_result"] != "FAIL"):
        return

    # HOP TWO -- the compliance hold is released.
    selection = get("selections", evaluation["selection_id"])
    interaction = None if selection is None else get("interactions",
                                                    selection["interaction_id"])
    if interaction is None or not interaction["compliance_hold"]:
        return
    interaction["compliance_hold"] = False
    touch(interaction)

    # HOP THREE -- the agent's findings and both indices.
    agent_id = evaluation["agent_id"]
    agent = get("agents", agent_id)
    findings = calc.open_compliance_findings(agent_id)
    if agent is None:
        return
    updates = {
        "open_compliance_findings": findings,
        "quality_index_rolling": calc.quality_index_rolling(agent_id),
        "quality_index_period": calc.quality_index_period(agent_id),
    }

    # HOP FOUR -- the coaching plans this evaluation justified are voided.
    if findings == 0:
        for plan in sorted_rows(rows("coaching_plans")):
            if (plan["agent_id"] == agent_id
                    and plan["source_evaluation_id"] == evaluation["id"]
                    and plan["status"] in ("ASSIGNED", "IN_PROGRESS")):
                plan["status"] = "VOIDED"
                touch(plan)
        if agent["coaching_state"] in ("REQUIRED", "ACTIVE"):
            updates["coaching_state"] = "CLEARED"
    derive.force(agent, updates)


@bp.post("/disputes/<dispute_id>/resolve")
@endpoint("QualityEvaluator")
def resolve_dispute(dispute_id):
    payload = body()
    outcome = shape.want_enum(payload, "outcome", OUTCOMES)
    note = shape.want_string(payload, "outcome_note", required=False)
    adjusted = shape.want_item_scores(payload, "adjusted_item_scores", required=False)

    dispute = require("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    evaluation = segregation(dispute)
    if dispute["status"] != "UNDER_REVIEW":
        fail("ERR_DISPUTE_NOT_RESOLVABLE", "only an UNDER_REVIEW dispute may be resolved")
    if dispute["reviewer_evaluator_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER",
             "only the reviewer who picked this dispute up may resolve it")

    if outcome == "NEEDS_MORE_INFO":
        _resolve_needs_more_info(dispute, note, adjusted)
    elif outcome == "REJECTED":
        _resolve_rejected(dispute, evaluation, note, adjusted)
    else:
        _resolve_upheld(dispute, evaluation, note, adjusted)
    return ok(view(dispute))


@bp.post("/disputes/<dispute_id>/respond")
@endpoint("Agent")
def respond_dispute(dispute_id):
    payload = body()
    additional = shape.want_string(payload, "additional_rationale")

    dispute = require("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    if dispute["agent_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER", "only the filing agent may respond")
    if dispute["status"] != "NEEDS_MORE_INFO":
        fail("ERR_DISPUTE_NOT_RESPONDABLE",
             "only a NEEDS_MORE_INFO dispute may be responded to")

    dispute["rationale"] = "%s | %s" % (dispute["rationale"], additional)
    dispute["status"] = "SUBMITTED"
    dispute["reviewer_evaluator_id"] = None
    touch(dispute)
    return ok(view(dispute))


@bp.get("/disputes/<dispute_id>")
@endpoint(*READ_ROLES)
def read_dispute(dispute_id):
    return ok(view(require("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")))


@bp.get("/disputes")
@endpoint(*LIST_ROLES)
def list_disputes():
    limit, offset = shape.pagination()
    evaluation_id = shape.query_str("evaluation_id")
    agent_id = shape.query_str("agent_id")
    reviewer_id = shape.query_str("reviewer_evaluator_id")
    status = shape.query_enum("status", DISPUTE_STATUSES)
    items = sorted_rows(rows("disputes"))
    if evaluation_id is not None:
        items = [d for d in items if d["evaluation_id"] == evaluation_id]
    if agent_id is not None:
        items = [d for d in items if d["agent_id"] == agent_id]
    if reviewer_id is not None:
        items = [d for d in items if d.get("reviewer_evaluator_id") == reviewer_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
