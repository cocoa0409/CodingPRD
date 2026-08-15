"""Feedback ticket endpoints."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_int, require_number, require_enum,
    optional_string, stamp_new, touch,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
)
from services.serializers import public
from services.calculations import feedback_priority_score

bp = make_blueprint("tickets")


def _get_ticket(tid):
    t = db.tickets.get(tid)
    if t is None:
        raise_error(ERR_NOT_FOUND, "Feedback ticket not found")
    return t


@bp.route("/playtests/feedback-tickets", methods=["POST"])
def create_ticket():
    require_roles("Moderator", "Researcher")
    body = get_payload()
    study_id = require_string(body, "study_id")
    title = require_string(body, "title")
    severity = require_enum(body, "severity", ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
    reach_count = require_int(body, "reach_count", minimum=0)
    reproducibility_pct = require_number(body, "reproducibility_pct", minimum=0, maximum=1)
    session_id = body.get("session_id")
    survey_response_id = body.get("survey_response_id")
    if session_id is not None and not isinstance(session_id, str):
        raise_error(ERR_INVALID_REQUEST, "session_id must be a string")
    if survey_response_id is not None and not isinstance(survey_response_id, str):
        raise_error(ERR_INVALID_REQUEST, "survey_response_id must be a string")

    study = db.studies.get(study_id)
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    if session_id is not None:
        session = db.sessions.get(session_id)
        if session is None:
            raise_error(ERR_NOT_FOUND, "Session not found")
        if session["study_id"] != study_id:
            raise_error(ERR_INVALID_REQUEST, "session_id does not belong to the ticket's study")
    if survey_response_id is not None:
        resp = db.responses.get(survey_response_id)
        if resp is None:
            raise_error(ERR_NOT_FOUND, "Survey response not found")
        instrument = db.instruments.get(resp["instrument_id"])
        if instrument is None or instrument["study_id"] != study_id:
            raise_error(ERR_INVALID_REQUEST,
                        "survey_response_id does not belong to the ticket's study")

    rec = {
        "study_id": study_id,
        "session_id": session_id,
        "survey_response_id": survey_response_id,
        "title": title,
        "severity": severity,
        "reach_count": reach_count,
        "reproducibility_pct": reproducibility_pct,
        "priority_score": None,
        "priority_tier": None,
        "backlog_target": None,
        "status": "NEW",
    }
    stamp_new(rec)
    db.tickets[rec["id"]] = rec
    return success(public(rec, "ticket"), status=201)


@bp.route("/playtests/feedback-tickets", methods=["GET"])
def list_tickets():
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.tickets.values())
    for param in ("study_id", "session_id", "survey_response_id", "status", "priority_tier"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if str(t.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(t, "ticket") for t in page], status=200, pagination=pagination)


@bp.route("/playtests/feedback-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator")
    t = _get_ticket(tid)
    return success(public(t, "ticket"), status=200)


@bp.route("/playtests/feedback-tickets/<tid>/triage", methods=["POST"])
def triage_ticket(tid):
    require_roles("Researcher")
    t = _get_ticket(tid)
    if t["status"] not in ("NEW", "NEEDS_INFO"):
        raise_error(ERR_INVALID_STATE, "Ticket must be NEW or NEEDS_INFO to triage")
    score, tier = feedback_priority_score(t)
    t["priority_score"] = score
    t["priority_tier"] = tier
    t["status"] = "TRIAGED"
    touch(t)
    return success(public(t, "ticket"), status=200)


@bp.route("/playtests/feedback-tickets/<tid>/request-info", methods=["POST"])
def ticket_request_info(tid):
    require_roles("Researcher")
    t = _get_ticket(tid)
    if t["status"] != "TRIAGED":
        raise_error(ERR_INVALID_STATE, "Ticket must be TRIAGED to request info")
    t["status"] = "NEEDS_INFO"
    touch(t)
    return success(public(t, "ticket"), status=200)


@bp.route("/playtests/feedback-tickets/<tid>/route", methods=["POST"])
def route_ticket(tid):
    require_roles("Researcher")
    t = _get_ticket(tid)
    body = get_payload()
    target = require_enum(body, "backlog_target",
                          ("GAMEPLAY", "PERFORMANCE", "UX", "AUDIO", "INFRA"))
    if t["status"] != "TRIAGED":
        raise_error(ERR_INVALID_STATE, "Ticket must be TRIAGED to route")
    t["status"] = "ROUTED"
    t["backlog_target"] = target
    touch(t)
    return success(public(t, "ticket"), status=200)


@bp.route("/playtests/feedback-tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    require_roles("Researcher")
    t = _get_ticket(tid)
    if t["status"] != "ROUTED":
        raise_error(ERR_INVALID_STATE, "Ticket must be ROUTED to resolve")
    t["status"] = "RESOLVED"
    touch(t)
    return success(public(t, "ticket"), status=200)


@bp.route("/playtests/feedback-tickets/<tid>/mark-wont-fix", methods=["POST"])
def wont_fix_ticket(tid):
    require_roles("Researcher")
    t = _get_ticket(tid)
    if t["status"] != "ROUTED":
        raise_error(ERR_INVALID_STATE, "Ticket must be ROUTED to mark won't-fix")
    t["status"] = "WONT_FIX"
    touch(t)
    return success(public(t, "ticket"), status=200)
