"""Hiring decisions: quorum gate, SoD, snapshot fields, FILLED/DECIDED
auto-transitions (PRD §3.8)."""
import db
import serializers
import util
from errors import (api_err, err_invalid_request, err_not_found, err_ownership,
                    err_ref_not_found)
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, filter_params, new_id, next_seq, paginate, req_enum, sort_records

bp = Blueprint("decisions", __name__)

READ_ROLES = ["DecisionOfficer", "HiringManager", "ComplianceOfficer",
              "TalentAssessmentAdmin", "Candidate"]
DECISIONS = ["ADVANCE", "HOLD", "REJECT"]


@bp.get("/talent/decisions")
def list_decisions():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["cycle_id", "candidate_id"])
    if ctx.role == "Candidate":
        if "candidate_id" in filters and filters["candidate_id"] != ctx.user_id:
            raise err_ownership("Candidate must filter by own candidate_id")
    recs = []
    for d in sort_records(list(db.stores["decisions"].values())):
        if "cycle_id" in filters and d["cycle_id"] != filters["cycle_id"]:
            continue
        if "candidate_id" in filters and d["candidate_id"] != filters["candidate_id"]:
            continue
        recs.append(serializers.decision(d))
    return paginate(recs)


@bp.get("/talent/decisions/<did>")
def get_decision(did):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    d = db.stores["decisions"].get(did)
    if d is None:
        raise err_not_found("HiringDecision not found")
    if ctx.role == "Candidate" and d["candidate_id"] != ctx.user_id:
        raise err_ownership("Candidate may only read own decisions")
    return success_object(serializers.decision(d))


@bp.post("/talent/cycles/<cid>/decisions")
def create_decision(cid):
    ctx = authenticate()
    require_roles(ctx, ["DecisionOfficer"])
    cyc = db.stores["cycles"].get(cid)
    if cyc is None:
        raise err_not_found("AssessmentCycle not found")
    body = util.get_body()
    candidate_id = body.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise err_invalid_request("candidate_id is required")
    candidate = db.stores["candidates"].get(candidate_id)
    if candidate is None:
        raise err_ref_not_found("candidate_id does not resolve")
    req = db.stores["requisitions"].get(cyc["requisition_id"])
    # Tier 7 gates, PRD §3.8 order: requisition OPEN -> assessment COMPLETED
    if req is None or req["status"] != "OPEN":
        raise api_err("ERR_REQUISITION_NOT_OPEN", "Requisition must be OPEN")
    assessment = None
    for a in db.stores["assessments"].values():
        if a["cycle_id"] == cid and a["candidate_id"] == candidate_id:
            assessment = a
            break
    if assessment is None or assessment["admin_status"] != "COMPLETED":
        raise api_err("ERR_ASSESSMENT_NOT_COMPLETED",
                      "The candidate's assessment in this cycle must be COMPLETED")
    # Tier 9 SoD: decider must not equal any quorum scorecard's interviewer
    sessions_evaluated = [
        s for s in db.stores["sessions"].values()
        if s["cycle_id"] == cid and s["candidate_id"] == candidate_id
        and s["status"] in ("COMPLETED", "SCORED")
    ]
    session_ids = {s["id"] for s in sessions_evaluated}
    submitted_cards = [
        sc for sc in db.stores["scorecards"].values()
        if sc["session_id"] in session_ids and sc["status"] == "SUBMITTED"
    ]
    for sc in submitted_cards:
        if sc["interviewer_id"] == ctx.user_id:
            raise api_err("ERR_SEGREGATION_OF_DUTIES",
                          "Decision officer authored a quorum scorecard for this candidate")
    # Tier 10: duplicate decision then quorum
    if core.finalized_decision(cid, candidate_id) is not None:
        raise api_err("ERR_DECISION_ALREADY_FINALIZED",
                      "A decision already exists for this candidate in this cycle")
    required = max(2, min(3, len(sessions_evaluated)))
    submitted = len(submitted_cards)
    if submitted < required:
        raise api_err("ERR_QUORUM_NOT_MET",
                      "Submitted scorecards do not meet the required quorum")
    # Tier 16: rationale length examined last
    decision_val = req_enum(body, "decision", DECISIONS)
    rationale = body.get("rationale")
    if not isinstance(rationale, str):
        raise err_invalid_request("rationale is required")
    if len(rationale) < 50:
        raise api_err("ERR_RATIONALE_TOO_SHORT",
                      "rationale must be at least 50 characters")
    now = db.get_now()
    composite_snapshot = assessment.get("composite_score")
    if composite_snapshot is not None:
        composite_snapshot = core.d4(composite_snapshot)
    rec = {
        "id": new_id(),
        "cycle_id": cid,
        "candidate_id": candidate_id,
        "decision": decision_val,
        "rationale": rationale,
        "decided_by_user_id": ctx.user_id,
        "status": "FINALIZED",
        "composite_at_decision": composite_snapshot,
        "quorum_required_at_decision": required,
        "quorum_submitted_at_decision": submitted,
        "finalized_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["decisions"][rec["id"]] = rec
    # Side effects
    cyc["decisions_finalized_count"] += 1
    bump(cyc)
    core.recompute_retention_anchor(assessment)
    bump(assessment)
    if decision_val == "ADVANCE":
        req["filled_count"] += 1
        if req["status"] == "OPEN" and req["filled_count"] >= req["openings_count"]:
            req["status"] = "FILLED"
        bump(req)
    # Auto DECIDED: every COMPLETED assessment in a SCORING cycle is decided
    if cyc["posture"] == "SCORING":
        completed = [a for a in db.stores["assessments"].values()
                     if a["cycle_id"] == cid and a["admin_status"] == "COMPLETED"]
        if all(core.finalized_decision(cid, a["candidate_id"]) is not None
               for a in completed):
            cyc["posture"] = "DECIDED"
            bump(cyc)
    return success_object(serializers.decision(rec), 201)
