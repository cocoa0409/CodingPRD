"""Manual review assignment and verdicts (PRD 3.8)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derived
import response
import schema
import services
import views
from errors import fail
from schema import Field

bp = Blueprint("reviews", __name__)

ASSIGN_FIELDS = (
    Field("assigned_reviewer_user_id", "string", required=True, min_len=1, max_len=64),
)

DECISION_FIELDS = (
    Field("decision", "string", required=True, enum=("APPROVE", "REJECT", "RETURN_FOR_STEP_UP")),
)


def _case_or_404(case_id):
    case = db.get(db.REVIEW_CASES, case_id)
    if case is None:
        fail("ERR_REVIEW_CASE_NOT_FOUND")
    return case


@bp.post("/idv/manual-review-cases/<case_id>/assign")
def assign_case(case_id):
    caller = auth.authenticate((auth.REVIEW_MANAGER,))
    case = _case_or_404(case_id)
    values = schema.validate(schema.read_body(), ASSIGN_FIELDS)
    if case["state"] != "QUEUED":
        fail("ERR_REVIEW_CASE_STATE_INVALID")
    session = db.get(db.SESSIONS, case["session_id"])
    client = db.get(db.CLIENTS, session["client_id"]) if session is not None else None
    if client is None or derived.available_review_credits(client) < calc.CREDITS_PER_ASSIGNMENT:
        fail("ERR_REVIEW_CAPACITY_EXHAUSTED")

    case["state"] = "ASSIGNED"
    case["assigned_by_user_id"] = caller.user_id
    case["assigned_reviewer_user_id"] = values["assigned_reviewer_user_id"]
    db.touch(case)
    return response.object_response(views.review_case_view(case))


@bp.post("/idv/manual-review-cases/<case_id>/decision")
def decide_case(case_id):
    caller = auth.authenticate((auth.MANUAL_REVIEWER,))
    case = _case_or_404(case_id)
    if (case["assigned_reviewer_user_id"] is not None
            and case["assigned_reviewer_user_id"] != caller.user_id):
        fail("ERR_REVIEW_ASSIGNEE_MISMATCH")
    values = schema.validate(schema.read_body(), DECISION_FIELDS)
    session = db.get(db.SESSIONS, case["session_id"])
    if session is None or session["identity_state"] != "MANUAL_REVIEW":
        fail("ERR_SESSION_STATE_INVALID")
    if case["state"] != "ASSIGNED":
        fail("ERR_REVIEW_CASE_STATE_INVALID")
    if case["assigned_by_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    decision = values["decision"]
    if decision == "RETURN_FOR_STEP_UP":
        services.require_not_lapsed(session)

    now = clock.now()
    case["state"] = "DECIDED"
    case["decision"] = decision
    case["decided_by_user_id"] = caller.user_id
    case["decided_at"] = now
    db.touch(case)

    services.recompute_provisional(session)
    if decision == "APPROVE":
        services.terminate_session(session, caller, "VERIFIED", "MANUAL_OVERRIDE",
                                   manual_override=True, event_type="REVIEW_DECIDED",
                                   payload_summary="decision, identity_state, disposition_reason, "
                                                   "manual_override_flag, assurance_score_final")
    elif decision == "REJECT":
        services.terminate_session(session, caller, "REJECTED", "REVIEW_REJECTED",
                                   manual_override=True, event_type="REVIEW_DECIDED",
                                   payload_summary="decision, identity_state, disposition_reason, "
                                                   "manual_override_flag, assurance_score_final")
    else:
        session["identity_state"] = "AWAITING_EVIDENCE"
        db.touch(session)
        services.append_event(session, "REVIEW_DECIDED", caller, "decision, identity_state")
    return response.object_response(views.review_case_view(case))
