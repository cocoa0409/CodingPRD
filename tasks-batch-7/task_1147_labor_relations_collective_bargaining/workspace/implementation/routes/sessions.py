"""BargainingSession endpoints."""

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_AGREEMENT_NOT_BARGAINABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    ERR_MEDIATOR_CONFLICT,
    ERR_NEGOTIATOR_BUFFER_CONFLICT,
    ERR_SESSION_NOT_STARTED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_UNION_DECERTIFIED,
    ERR_UNION_TRUSTEED,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, page, parse_pagination,
    req_datetime, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object

bp = Blueprint("sessions", __name__)

SESSION_STATUSES = ("SCHEDULED", "IN_SESSION", "COMPLETED", "CANCELLED", "NO_SHOW")


@bp.post("/labor-relations/sessions")
def create_session():
    authenticate(["Negotiator"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    mediator_id = req_string(body, "mediator_id")
    lead_negotiator_id = req_string(body, "lead_negotiator_id")
    location = req_string(body, "location")
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")

    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")

    # Cross-entity state gate: agreement must be bargainable (priority 6)
    if not calc.is_bargainable(agreement, clock.now()):
        raise_err(ERR_AGREEMENT_NOT_BARGAINABLE, "Agreement is not bargainable")

    # Union standing (priority 8)
    union = lookup(db.unions, agreement["union_id"], "Union")
    if union["status"] == "TRUSTEED":
        raise_err(ERR_UNION_TRUSTEED, "Union is TRUSTEED; session scheduling is blocked")
    if union["status"] == "DECERTIFIED":
        raise_err(ERR_UNION_DECERTIFIED, "Union is DECERTIFIED; session scheduling is blocked")

    # Scalar temporal rule (priority 9)
    if start_at >= end_at or (end_at - start_at) > calc.SESSION_MAX_DURATION:
        raise_err(ERR_INVALID_TIME_RANGE, "start_at must be strictly before end_at and duration must not exceed 12 hours")

    # Interval conflicts (priority 10): mediator half-open first, then negotiator buffer
    for other in db.sessions.values():
        if other["status"] not in ("SCHEDULED", "IN_SESSION"):
            continue
        if other["mediator_id"] == mediator_id:
            # half-open [start_at, end_at) overlap; adjacency allowed
            if start_at < other["end_at"] and other["start_at"] < end_at:
                raise_err(ERR_MEDIATOR_CONFLICT, "Mediator %s has an overlapping session" % mediator_id)
        if other["lead_negotiator_id"] == lead_negotiator_id:
            # both intervals expanded by 45 minutes on each end; touching expanded
            # boundaries count as a conflict
            if (start_at - calc.NEGOTIATOR_BUFFER <= other["end_at"] + calc.NEGOTIATOR_BUFFER
                    and other["start_at"] - calc.NEGOTIATOR_BUFFER <= end_at + calc.NEGOTIATOR_BUFFER):
                raise_err(ERR_NEGOTIATOR_BUFFER_CONFLICT,
                          "Lead negotiator %s has a session within the 45-minute buffer" % lead_negotiator_id)

    session = new_entity()
    session.update({
        "agreement_id": agreement_id,
        "mediator_id": mediator_id,
        "lead_negotiator_id": lead_negotiator_id,
        "location": location,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
        "summary_note": None,
        "cancel_reason": None,
    })
    db.sessions[session["id"]] = session
    return success_object(serialize(session), status=201)


@bp.get("/labor-relations/sessions")
def list_sessions():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    mediator_id = request.args.get("mediator_id")
    status = request.args.get("status")
    items = list(db.sessions.values())
    if agreement_id is not None:
        items = [s for s in items if s["agreement_id"] == agreement_id]
    if mediator_id is not None:
        items = [s for s in items if s["mediator_id"] == mediator_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(s) for s in slice_], limit, offset, total)


@bp.get("/labor-relations/sessions/<session_id>")
def get_session(session_id):
    authenticate(ALL_ROLES)
    session = lookup(db.sessions, session_id, "BargainingSession")
    return success_object(serialize(session))


@bp.post("/labor-relations/sessions/<session_id>/state")
def transition_session(session_id):
    user_id, role = authenticate(["Negotiator", "ChiefNegotiator"])
    session = lookup(db.sessions, session_id, "BargainingSession")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in SESSION_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown session status: %s" % to_status)

    # Per-transition role gating: IN_SESSION / COMPLETED are ChiefNegotiator-only;
    # CANCELLED is shared with Negotiator.
    if to_status in ("IN_SESSION", "COMPLETED") and role != "ChiefNegotiator":
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only ChiefNegotiator may transition a session to %s" % to_status)
    if to_status in ("SCHEDULED", "NO_SHOW"):
        raise_err(ERR_INVALID_STATE, "Cannot transition a session to %s" % to_status)

    if to_status == "IN_SESSION":
        if session["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Only a SCHEDULED session can enter IN_SESSION")
        if clock.now() < session["start_at"]:
            raise_err(ERR_SESSION_NOT_STARTED, "The session has not started yet")

    elif to_status == "COMPLETED":
        summary_note = body.get("summary_note")
        if not isinstance(summary_note, str) or not summary_note.strip():
            raise_err(ERR_INVALID_REQUEST, "summary_note is required for COMPLETED")
        if session["status"] != "IN_SESSION":
            raise_err(ERR_INVALID_STATE, "Only an IN_SESSION session can be completed")
        session["summary_note"] = summary_note

    elif to_status == "CANCELLED":
        cancel_reason = body.get("cancel_reason")
        if not isinstance(cancel_reason, str) or not cancel_reason.strip():
            raise_err(ERR_INVALID_REQUEST, "cancel_reason is required for CANCELLED")
        if session["status"] != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "Only a SCHEDULED session can be cancelled")
        session["cancel_reason"] = cancel_reason

    session["status"] = to_status
    touch(session)
    return success_object(serialize(session))
