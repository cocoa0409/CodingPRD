"""Scorecards: submit/void with composite + calibration recompute (PRD §3.6)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, filter_params, paginate, sort_records

bp = Blueprint("scorecards", __name__)

READ_ROLES = ["TalentAssessmentAdmin", "ComplianceOfficer", "DecisionOfficer",
              "HiringManager", "Interviewer"]
Q4 = Decimal("0.0001")


def _get_scorecard_or_404(scid):
    sc = db.stores["scorecards"].get(scid)
    if sc is None:
        raise err_not_found("Scorecard not found")
    return sc


@bp.get("/talent/scorecards")
def list_scorecards():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["session_id", "interviewer_id", "candidate_id", "status"])
    if ctx.role == "Interviewer":
        if "interviewer_id" in filters and filters["interviewer_id"] != ctx.user_id:
            raise err_ownership("Interviewer must filter by own interviewer_id")
    recs = []
    for sc in sort_records(list(db.stores["scorecards"].values())):
        if "session_id" in filters and sc["session_id"] != filters["session_id"]:
            continue
        if "interviewer_id" in filters and sc["interviewer_id"] != filters["interviewer_id"]:
            continue
        if "candidate_id" in filters and sc["candidate_id"] != filters["candidate_id"]:
            continue
        if "status" in filters and sc["status"] != filters["status"]:
            continue
        recs.append(serializers.scorecard(sc))
    return paginate(recs)


@bp.get("/talent/scorecards/<scid>")
def get_scorecard(scid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    sc = _get_scorecard_or_404(scid)
    if ctx.role == "Interviewer" and sc["interviewer_id"] != ctx.user_id:
        raise err_ownership("Interviewer may only read own scorecards")
    return success_object(serializers.scorecard(sc))


def _assessment_for(sc):
    for a in db.stores["assessments"].values():
        if a["candidate_id"] == sc["candidate_id"]:
            sess = db.stores["sessions"].get(sc["session_id"])
            if sess is not None and a["cycle_id"] == sess["cycle_id"]:
                return a
    return None


@bp.post("/talent/scorecards/<scid>/submit")
def submit_scorecard(scid):
    ctx = authenticate()
    require_roles(ctx, ["Interviewer"])
    sc = _get_scorecard_or_404(scid)
    util.get_body()
    # Ownership: author only
    if sc["interviewer_id"] != ctx.user_id:
        raise err_ownership("Only the scorecard's author may submit it")
    if sc["status"] != "DRAFT":
        raise api_err("ERR_SCORECARD_NOT_DRAFT", "Scorecard must be DRAFT to submit")
    sess = db.stores["sessions"].get(sc["session_id"])
    if sess is None or sess["status"] != "COMPLETED":
        raise api_err("ERR_SESSION_NOT_COMPLETED", "Session must be COMPLETED")
    cyc = db.stores["cycles"].get(sess["cycle_id"])
    if cyc is not None:
        if cyc["posture"] == "FROZEN":
            raise api_err("ERR_CYCLE_FROZEN", "Cycle is FROZEN")
        if cyc["posture"] not in ("ACTIVE", "SCORING"):
            raise api_err("ERR_CYCLE_NOT_ACTIVE",
                          "Cycle posture must be ACTIVE or SCORING")
    now = db.get_now()
    if sess["completed_at"] is not None and now > sess["completed_at"] + timedelta(hours=72):
        raise api_err("ERR_SCORECARD_WINDOW_CLOSED",
                      "Submission window closed (72 hours after session completion)")
    # weighted_total: sum(weight_c * rating_c / scale_max_c), 4dp half-up
    guide = db.stores["guides"].get(sess["guide_id"])
    rubric = {i["competency_code"]: i for i in (guide["rubric_items"] if guide else [])}
    total = Decimal("0")
    for r in sc["ratings"]:
        item = rubric[r["competency_code"]]
        total += (Decimal(str(item["weight"])) * Decimal(r["rating"])
                  / Decimal(item["scale_max"]))
    sc["weighted_total"] = float(total.quantize(Q4, rounding=ROUND_HALF_UP))
    sc["status"] = "SUBMITTED"
    sc["submitted_at"] = now
    bump(sc)
    # Side effect 1: session COMPLETED -> SCORED
    sess["status"] = "SCORED"
    bump(sess)
    # Side effect 2: recompute the candidate assessment's composite
    a = _assessment_for(sc)
    if a is not None:
        core.compute_composite(a)
        bump(a)
    # Side effect 3: calibration recompute for author + panel peers
    core.recompute_calibration_for([(sess["cycle_id"], sess["candidate_id"])],
                                   extra_interviewer=sc["interviewer_id"])
    return success_object(serializers.scorecard(sc))


@bp.post("/talent/scorecards/<scid>/void")
def void_scorecard(scid):
    ctx = authenticate()
    require_roles(ctx, ["ComplianceOfficer"])
    sc = _get_scorecard_or_404(scid)
    if sc["status"] != "SUBMITTED":
        raise api_err("ERR_SCORECARD_NOT_SUBMITTED", "Scorecard must be SUBMITTED to void")
    sess = db.stores["sessions"].get(sc["session_id"])
    cycle_id = sess["cycle_id"] if sess else None
    if core.finalized_decision(cycle_id, sc["candidate_id"]) is not None:
        raise api_err("ERR_DECISION_ALREADY_FINALIZED",
                      "A FINALIZED decision exists for this candidate in this cycle")
    body = util.get_body()
    reason = body.get("void_reason")
    if not isinstance(reason, str) or len(reason) < 20:
        raise err_invalid_request("void_reason of at least 20 characters is required")
    now = db.get_now()
    sc["status"] = "VOIDED"
    sc["voided_at"] = now
    sc["void_reason"] = reason
    bump(sc)
    # Compensation: session SCORED -> COMPLETED
    if sess is not None and sess["status"] == "SCORED":
        sess["status"] = "COMPLETED"
        bump(sess)
    # Composite recompute
    a = _assessment_for(sc)
    if a is not None:
        core.compute_composite(a)
        bump(a)
    # Calibration recompute for affected interviewers
    if sess is not None:
        core.recompute_calibration_for([(sess["cycle_id"], sess["candidate_id"])],
                                       extra_interviewer=sc["interviewer_id"])
    return success_object(serializers.scorecard(sc))
