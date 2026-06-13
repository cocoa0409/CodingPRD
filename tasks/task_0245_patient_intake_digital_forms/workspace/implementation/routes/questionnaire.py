"""QuestionnaireResponse routes and risk scoring (PRD §3.8)."""
from flask import Blueprint, request

import db
import serialize
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_SESSION_EXPIRED,
    ERR_QUESTIONNAIRE_NOT_DRAFT,
    ERR_QUESTIONNAIRE_NOT_SUBMITTED,
    ERR_QUESTIONNAIRE_NOT_REVISABLE,
    ERR_QUESTIONNAIRE_INCOMPLETE,
)
from middleware import require_roles
from response import success, success_list
from services import calculations
from services.common import touch, require_string
from services.lookups import get_session, get_questionnaire
from services.pagination import paginate
from services import sessions as S

bp = Blueprint("questionnaire", __name__)


def _validate_sections(value):
    """answered_sections: array of {section_key, risk_weight in 0..10}."""
    if not isinstance(value, list):
        raise err(ERR_INVALID_REQUEST, "answered_sections must be an array")
    out = []
    for s in value:
        if not isinstance(s, dict):
            raise err(ERR_INVALID_REQUEST, "each answered_section must be an object")
        section_key = s.get("section_key")
        risk_weight = s.get("risk_weight")
        if not isinstance(section_key, str) or section_key == "":
            raise err(ERR_INVALID_REQUEST, "section_key must be a non-empty string")
        if isinstance(risk_weight, bool) or not isinstance(risk_weight, int):
            raise err(ERR_INVALID_REQUEST, "risk_weight must be an integer")
        if risk_weight < 0 or risk_weight > 10:
            raise err(ERR_INVALID_REQUEST, "risk_weight must be 0-10")
        out.append({"section_key": section_key, "risk_weight": risk_weight})
    return out


def _first_in_progress(session):
    if session["workflow_status"] == "DRAFT":
        if S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired")
        session["workflow_status"] = "IN_PROGRESS"
        touch(session)


@bp.route("/questionnaire-responses", methods=["POST"])
@require_roles("FrontDeskStaff", "Patient")
def create_questionnaire():
    body = request.get_json(silent=True) or {}
    intake_session_id = require_string(body, "intake_session_id")
    session = get_session(intake_session_id)

    answered = body.get("answered_sections")
    answered_sections = _validate_sections(answered) if answered is not None else []

    with db.LOCK:
        _first_in_progress(session)
        now = db.now_iso()
        q = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "intake_session_id": intake_session_id,
            "answered_sections": answered_sections,
            "provisional_risk_score": 0,
            "final_risk_score": None,
            "high_risk_flag": False,
            "status": "DRAFT",
        }
        db.questionnaire_responses[q["id"]] = q
    return success(serialize.questionnaire_response(q), status=201)


@bp.route("/questionnaire-responses/<qid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk", "Patient")
def get_questionnaire_route(qid):
    q = get_questionnaire(qid)
    return success(serialize.questionnaire_response(q), status=200)


@bp.route("/questionnaire-responses", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk", "Patient")
def list_questionnaires():
    records = list(db.questionnaire_responses.values())
    val = request.args.get("intake_session_id")
    if val is not None:
        records = [r for r in records if r["intake_session_id"] == val]
    items, limit, offset, total = paginate(records, serialize.questionnaire_response)
    return success_list(items, limit, offset, total)


@bp.route("/questionnaire-responses/<qid>", methods=["PATCH"])
@require_roles("Patient", "FrontDeskStaff")
def patch_questionnaire(qid):
    body = request.get_json(silent=True) or {}
    q = get_questionnaire(qid)
    with db.LOCK:
        if q["status"] != "DRAFT":
            raise err(ERR_QUESTIONNAIRE_NOT_DRAFT, "questionnaire not DRAFT")
        if "answered_sections" not in body or body["answered_sections"] is None:
            raise err(ERR_INVALID_REQUEST, "answered_sections required")
        q["answered_sections"] = _validate_sections(body["answered_sections"])
        touch(q)
    return success(serialize.questionnaire_response(q), status=200)


@bp.route("/questionnaire-responses/<qid>/submit", methods=["POST"])
@require_roles("Patient")
def submit_questionnaire(qid):
    q = get_questionnaire(qid)
    with db.LOCK:
        if q["status"] != "DRAFT":
            raise err(ERR_QUESTIONNAIRE_NOT_DRAFT, "questionnaire not DRAFT")
        session = db.intake_sessions[q["intake_session_id"]]
        if session["workflow_status"] in {"EXPIRED", "CANCELLED"} or S.is_expired(session):
            raise err(ERR_SESSION_EXPIRED, "session expired/cancelled")
        q["provisional_risk_score"] = calculations.provisional_risk_score(
            q["answered_sections"])
        q["status"] = "SUBMITTED"
        touch(q)
    return success(serialize.questionnaire_response(q), status=200)


@bp.route("/questionnaire-responses/<qid>/accept", methods=["POST"])
@require_roles("FrontDeskStaff")
def accept_questionnaire(qid):
    q = get_questionnaire(qid)
    with db.LOCK:
        if q["status"] != "SUBMITTED":
            raise err(ERR_QUESTIONNAIRE_NOT_SUBMITTED, "questionnaire not SUBMITTED")
        session = db.intake_sessions[q["intake_session_id"]]
        provider = db.providers[session["provider_id"]]
        required_sections = provider.get("questionnaire_required_sections") or []
        answered_keys = {s["section_key"] for s in q["answered_sections"]}
        if not all(k in answered_keys for k in required_sections):
            raise err(ERR_QUESTIONNAIRE_INCOMPLETE, "missing required section")

        final = calculations.final_risk_score(q["answered_sections"], required_sections)
        high = calculations.is_high_risk(final)
        q["final_risk_score"] = final
        q["high_risk_flag"] = high
        # High-risk lands in FLAGGED (does not satisfy forms_complete) (PRD §3.8).
        q["status"] = "FLAGGED" if high else "ACCEPTED"
        touch(q)
        # ACCEPTED bubbles up; FLAGGED does not satisfy completeness but the
        # recompute is harmless (it will read as incomplete).
        S.bubble_up(session)
    return success(serialize.questionnaire_response(q), status=200)


@bp.route("/questionnaire-responses/<qid>/revise", methods=["POST"])
@require_roles("Patient")
def revise_questionnaire(qid):
    q = get_questionnaire(qid)
    with db.LOCK:
        if q["status"] not in {"SUBMITTED", "FLAGGED"}:
            raise err(ERR_QUESTIONNAIRE_NOT_REVISABLE, "questionnaire not revisable")
        q["status"] = "DRAFT"
        q["final_risk_score"] = None
        q["high_risk_flag"] = False
        touch(q)
        session = db.intake_sessions[q["intake_session_id"]]
        S.bubble_up(session)
    return success(serialize.questionnaire_response(q), status=200)
