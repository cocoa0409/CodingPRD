"""ProvostDecision endpoints (PRD §3.7)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_DECISION_NOT_FOUND,
    ERR_CASE_STAGE_FORBIDDEN,
    ERR_SOD_DECISION_BY_CASE_CREATOR,
    ERR_SCORE_BELOW_THRESHOLD,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calculations as calc
from services.core import new_record, touch
from util import CLOCK, fmt_dt, D
from validate import get_body, req_str, req_enum, opt_nullable_str, raw_str

bp = Blueprint("decisions", __name__)

DECISIONS = {"GRANT_TENURE", "GRANT_PROMOTION", "GRANT_BOTH", "DENY", "DEFER"}
GRANTING = {"GRANT_TENURE", "GRANT_PROMOTION", "GRANT_BOTH"}


@bp.post("/decisions")
def create_decision():
    caller = authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 4: case FK existence.
    case = None
    case_id_raw = raw_str(body, "case_id")
    if case_id_raw is not None:
        case = db["cases"].get(case_id_raw)
        if case is None:
            raise_error(ERR_CASE_NOT_FOUND, "case_id does not resolve")
    # Priority 6: decision recording requires PROVOST_REVIEW.
    if case is not None and case["stage"] != "PROVOST_REVIEW":
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    "decision recording requires the case to be in PROVOST_REVIEW")
    # Priority 8: the recorder must differ from the case creator (SoD).
    if case is not None and caller.user_id == case["created_by_user_id"]:
        raise_error(ERR_SOD_DECISION_BY_CASE_CREATOR,
                    "the case creator may not record its provost decision")
    # Priority 9: shape.
    req_str(body, "case_id")
    decision = req_enum(body, "decision", DECISIONS)
    rationale_text = req_str(body, "rationale_text")
    override_rationale = opt_nullable_str(body, "override_rationale", None)
    # Priority 11: granting decisions need score >= 0.60 or a non-empty override.
    if decision in GRANTING:
        score = case["recommendation_score"]
        has_override = isinstance(override_rationale, str) and override_rationale.strip() != ""
        if not has_override and (score is None or D(str(score)) < calc.GRANT_THRESHOLD):
            raise_error(ERR_SCORE_BELOW_THRESHOLD,
                        "recommendation_score below 0.60 without an override rationale")
    now = CLOCK.now()
    rec = new_record("decisions", {
        "case_id": case["id"],
        "decision": decision,
        "rationale_text": rationale_text,
        "override_rationale": override_rationale,
        "recorded_by_user_id": caller.user_id,
        "decided_at": fmt_dt(now),
        "notification_deadline": fmt_dt(now + timedelta(days=calc.NOTIFICATION_WINDOW_DAYS)),
        "notification_sent_at": None,
        "status": "RECORDED",
    })
    # Candidate cascade (PRD §3.7).
    candidate = db["candidates"].get(case["candidate_id"])
    if candidate is not None:
        if decision == "DENY":
            candidate["status"] = "NOT_RENEWED"
            touch(candidate)
        elif decision in ("GRANT_TENURE", "GRANT_BOTH") and case["seeking_tenure"]:
            candidate["status"] = "TENURED"
            touch(candidate)
    case["stage"] = "DECIDED"
    touch(case)
    return success_object(public(rec), status=201)


@bp.get("/decisions")
def list_decisions():
    return list_response("decisions", {
        "case_id": request.args.get("case_id"),
    })


@bp.get("/decisions/<rid>")
def get_decision(rid):
    return get_one("decisions", rid, ERR_DECISION_NOT_FOUND)
