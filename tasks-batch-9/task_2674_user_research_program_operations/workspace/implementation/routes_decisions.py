"""Roadmap decisions and the intake funnel (PRD 3.1)."""
from decimal import Decimal as D

from flask import Blueprint, g

import serializers
from auth import ALL_ROLES, require_roles
from calc import (
    LOCK_MIN_CONFIDENCE,
    decision_evidence_confidence,
    method_recommendation,
    request_priority_score,
    set_field,
)
from clock import clock
from envelope import created, ok, paged_listing
from errors import ApiError
from store import by_created, db
from validators import (
    body,
    decision_or_404,
    filter_enum,
    opt_enum,
    opt_str,
    ref,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    request_or_404,
)

bp = Blueprint("decisions", __name__)

REVERSIBILITY = ("IRREVERSIBLE", "REVERSIBLE")
QUESTION_TYPES = ("DISCOVERY", "EVALUATIVE", "BEHAVIORAL_LONGITUDINAL", "MEASUREMENT")
EVIDENCE_GAPS = ("NONE", "PARTIAL", "FULL")
METHODS = ("INTERVIEW", "USABILITY_TEST", "DIARY_STUDY", "SURVEY")
TRIAGE_OUTCOMES = ("APPROVED", "NEEDS_REFRAMING", "REJECTED")
DECISION_STATUSES = ("OPEN", "LOCKED")
REQUEST_STATUSES = ("SUBMITTED", "APPROVED", "NEEDS_REFRAMING", "REJECTED", "IN_STUDY", "CLOSED")


@bp.post("/roadmap-decisions")
@require_roles("Stakeholder", "ResearchOpsAdmin")
def create_decision():
    data = body()
    row = db.new("decisions", {
        "title": req_str(data, "title", max_len=200),
        "decision_deadline": req_datetime(data, "decision_deadline"),
        "reversibility": req_enum(data, "reversibility", REVERSIBILITY),
        "impacted_user_count": req_int(data, "impacted_user_count", minimum=0),
        "status": "OPEN",
        "evidence_confidence": D("0.00"),
        "locked_at": None,
    })
    return created(serializers.decision(row))


@bp.post("/roadmap-decisions/<decision_id>/lock")
@require_roles("Stakeholder")
def lock_decision(decision_id):
    decision = decision_or_404(decision_id)
    if decision["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN decision can be locked.")
    confidence = decision_evidence_confidence(decision)
    if confidence < LOCK_MIN_CONFIDENCE:
        raise ApiError(
            "ERR_CONFIDENCE_BELOW_LOCK_THRESHOLD",
            "Recomputed evidence confidence is below the 0.60 lock threshold.",
        )
    set_field(decision, "evidence_confidence", confidence)
    set_field(decision, "status", "LOCKED")
    set_field(decision, "locked_at", clock.now())
    return ok(serializers.decision(decision))


@bp.get("/roadmap-decisions/<decision_id>")
@require_roles(*ALL_ROLES)
def read_decision(decision_id):
    return ok(serializers.decision(decision_or_404(decision_id)))


@bp.get("/roadmap-decisions/<decision_id>/research-requests")
@require_roles(*ALL_ROLES)
def list_decision_requests(decision_id):
    decision = decision_or_404(decision_id)
    status = filter_enum("status", REQUEST_STATUSES)
    rows = [r for r in db.requests.values() if r["roadmap_decision_id"] == decision["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = _by_priority(rows)
    return paged_listing(rows, serializers.research_request)


def _by_priority(rows):
    """priority_score DESC then created_at ASC; an unscored request sorts last."""
    return sorted(
        rows,
        key=lambda r: (
            1 if r["priority_score"] is None else 0,
            -D(r["priority_score"]) if r["priority_score"] is not None else D("0"),
            r["created_at"],
            r["_seq"],
        ),
    )


@bp.post("/research-requests")
@require_roles("Stakeholder", "Researcher", "ResearchLead")
def create_request():
    data = body()
    decision_or_404(ref(data, "roadmap_decision_id"))
    row = db.new("requests", {
        "roadmap_decision_id": req_str(data, "roadmap_decision_id"),
        "requester_user_id": g.user_id,
        "question": req_str(data, "question", max_len=500),
        "question_type": req_enum(data, "question_type", QUESTION_TYPES),
        "evidence_gap": req_enum(data, "evidence_gap", EVIDENCE_GAPS),
        "status": "SUBMITTED",
        "priority_score": None,
        "recommended_method": None,
        "approved_method": None,
        "revision_round": 0,
        "triage_reason": None,
        "triaged_at": None,
    })
    return created(serializers.research_request(row))


@bp.post("/research-requests/<request_id>/triage")
@require_roles("ResearchLead")
def triage_request(request_id):
    row = request_or_404(request_id)
    data = body()
    outcome = req_enum(data, "outcome", TRIAGE_OUTCOMES)
    reason = opt_str(data, "reason")
    override = opt_enum(data, "method_override", METHODS)
    current = row["status"]
    if not ((current == "SUBMITTED" and outcome in TRIAGE_OUTCOMES)
            or (current == "NEEDS_REFRAMING" and outcome == "REJECTED")):
        raise ApiError("ERR_INVALID_STATE", "That triage outcome is not available from %s." % current)
    decision = db.decisions.get(row["roadmap_decision_id"])
    set_field(row, "priority_score", request_priority_score(row, decision))
    set_field(row, "recommended_method", method_recommendation(row, decision))
    set_field(row, "triaged_at", clock.now())
    set_field(row, "triage_reason", reason)
    if current == "SUBMITTED" and outcome == "APPROVED":
        set_field(row, "approved_method", override if override is not None else row["recommended_method"])
    set_field(row, "status", outcome)
    return ok(serializers.research_request(row))


@bp.post("/research-requests/<request_id>/resubmit")
@require_roles("Stakeholder", "Researcher", "ResearchLead")
def resubmit_request(request_id):
    existing = db.requests.get(request_id)
    if existing is not None and existing["requester_user_id"] != g.user_id:
        raise ApiError("ERR_OWNERSHIP_REQUIRED", "Only the recorded requester may resubmit.")
    row = request_or_404(request_id)
    data = body()
    question = req_str(data, "question", max_len=500)
    question_type = req_enum(data, "question_type", QUESTION_TYPES)
    evidence_gap = req_enum(data, "evidence_gap", EVIDENCE_GAPS)
    if row["status"] != "NEEDS_REFRAMING":
        raise ApiError("ERR_INVALID_STATE", "Only a NEEDS_REFRAMING request can be resubmitted.")
    if row["revision_round"] >= 2:
        raise ApiError("ERR_REVISION_LIMIT_REACHED", "At most two reframing rounds are permitted.")
    set_field(row, "question", question)
    set_field(row, "question_type", question_type)
    set_field(row, "evidence_gap", evidence_gap)
    set_field(row, "revision_round", row["revision_round"] + 1)
    set_field(row, "priority_score", None)
    set_field(row, "recommended_method", None)
    set_field(row, "approved_method", None)
    set_field(row, "status", "SUBMITTED")
    return ok(serializers.research_request(row))


@bp.get("/research-requests/<request_id>")
@require_roles(*ALL_ROLES)
def read_request(request_id):
    return ok(serializers.research_request(request_or_404(request_id)))
