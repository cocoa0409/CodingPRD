"""Rounding sessions, deficiency ticketing and remediation (PRD 3.5)."""

from flask import Blueprint, g, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_action_role, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_session,
    get_standard,
    get_ticket,
    get_unit,
    opt_str,
    page,
    pagination,
    req_dt,
    req_enum,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("rounding", __name__)

TICKET_ACTIONS = ("START_WORK", "MARK_REMEDIATED", "VERIFY", "FAIL_VERIFICATION", "ESCALATE")
TICKET_ACTION_ROLES = {
    "START_WORK": ("SafetyOfficer", "UnitManager"),
    "MARK_REMEDIATED": ("SafetyOfficer", "UnitManager"),
    "VERIFY": ("SafetyOfficer",),
    "FAIL_VERIFICATION": ("SafetyOfficer",),
    "ESCALATE": ("SafetyOfficer",),
}


# --------------------------------------------------------------------------
# rounding sessions
# --------------------------------------------------------------------------
@bp.post("/accreditation/rounding-sessions")
def open_session():
    require_roles("SafetyOfficer")
    b = body()
    unit_id = req_str(b, "unit_id")
    round_type = req_enum(b, "round_type", calc.ROUND_TYPES)
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")

    # Rung 6
    unit = get_unit(unit_id)

    # Rung 9
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_INTERVAL")

    # Rung 35 — closed interval, second-exact, aggregate capacity two.
    new_start = calc.floor_to_second(window_start)
    new_end = calc.floor_to_second(window_end)
    intersecting = 0
    for existing in rows(db.rounding_sessions):
        if existing["unit_id"] != unit["id"] or existing["round_type"] != round_type:
            continue
        if existing["state"] != "OPEN":
            continue
        ex_start = calc.floor_to_second(existing["window_start"])
        ex_end = calc.floor_to_second(existing["window_end"])
        if ex_start <= new_end and ex_end >= new_start:
            intersecting += 1
    if intersecting >= calc.ROUNDING_CONCURRENCY_LIMIT:
        raise ApiError("ERR_ROUNDING_CAPACITY_EXCEEDED")

    session = base_entity("RoundingSession")
    session.update(
        {
            "unit_id": unit["id"],
            "round_type": round_type,
            "window_start": window_start,
            "window_end": window_end,
            "state": "OPEN",
            "deficiency_count": 0,
            "closed_at": None,
        }
    )
    db.rounding_sessions[session["id"]] = session
    return object_response(serialize.rounding_session(session), 201)


@bp.get("/accreditation/rounding-sessions/<session_id>")
def read_session(session_id):
    require_roles(*ALL_ROLES)
    session = get_session(session_id)
    return object_response(serialize.rounding_session(session))


@bp.get("/accreditation/rounding-sessions")
def list_sessions():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    result = rows(db.rounding_sessions)
    unit_id = request.args.get("unit_id")
    round_type = request.args.get("round_type")
    state = request.args.get("state")
    if unit_id:
        result = [s for s in result if s["unit_id"] == unit_id]
    if round_type:
        result = [s for s in result if s["round_type"] == round_type]
    if state:
        result = [s for s in result if s["state"] == state]
    items, total = page(result, limit, offset)
    return array_response([serialize.rounding_session(s) for s in items], limit, offset, total)


@bp.post("/accreditation/rounding-sessions/<session_id>/close")
def close_session(session_id):
    require_roles("SafetyOfficer")
    body()
    session = get_session(session_id)

    # Rung 13
    if session["state"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 25
    for ticket in db.tickets.values():
        if ticket["rounding_session_id"] == session["id"] and ticket["state"] == "ESCALATED":
            raise ApiError("ERR_ESCALATED_TICKET_BLOCKS_CLOSE")

    session["state"] = "CLOSED"
    session["closed_at"] = db.clock
    touch(session)
    return object_response(serialize.rounding_session(session))


# --------------------------------------------------------------------------
# deficiency tickets
# --------------------------------------------------------------------------
@bp.post("/accreditation/rounding-sessions/<session_id>/deficiencies")
def raise_deficiency(session_id):
    require_roles("SafetyOfficer")
    b = body()
    standard_id = req_str(b, "standard_id")
    description = req_str(b, "description")
    severity = req_enum(b, "severity", calc.SEVERITIES)

    # Rung 5
    session = get_session(session_id)
    # Rung 6
    standard = get_standard(standard_id)

    # Rung 15
    if session["state"] != "OPEN":
        raise ApiError("ERR_SESSION_ALREADY_CLOSED")

    unit = db.units[session["unit_id"]]

    # Pinned order (PRD 3.5): steps 1-4 read the band as persisted before this
    # ticket exists, steps 6-7 then write the consequences.
    band_snapshot = unit["readiness_band"]
    due_at, accelerated = calc.deficiency_due_at(db.clock, severity, band_snapshot)
    penalty_points = calc.SEVERITY_POINTS[severity]

    ticket = base_entity("DeficiencyTicket")
    ticket.update(
        {
            "rounding_session_id": session["id"],
            "standard_id": standard["id"],
            "description": description,
            "severity": severity,
            "state": "OPEN",
            "penalty_points": penalty_points,
            "due_at": due_at,
            "accelerated": accelerated,
            "verified_by_user_id": None,
            "failed_verification_count": 0,
        }
    )
    db.tickets[ticket["id"]] = ticket

    session["deficiency_count"] += 1
    touch(session)

    unit["open_deficiency_penalty_points"] += penalty_points
    touch(unit)
    cascade.refresh_unit_posture(unit)

    return object_response(serialize.ticket(ticket), 201)


@bp.get("/accreditation/deficiency-tickets/<ticket_id>")
def read_ticket(ticket_id):
    require_roles(*ALL_ROLES)
    ticket = get_ticket(ticket_id)
    return object_response(serialize.ticket(ticket))


@bp.get("/accreditation/deficiency-tickets")
def list_tickets():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    result = rows(db.tickets)
    session_id = request.args.get("rounding_session_id")
    standard_id = request.args.get("standard_id")
    state = request.args.get("state")
    severity = request.args.get("severity")
    if session_id:
        result = [t for t in result if t["rounding_session_id"] == session_id]
    if standard_id:
        result = [t for t in result if t["standard_id"] == standard_id]
    if state:
        result = [t for t in result if t["state"] == state]
    if severity:
        result = [t for t in result if t["severity"] == severity]
    items, total = page(result, limit, offset)
    return array_response([serialize.ticket(t) for t in items], limit, offset, total)


@bp.post("/accreditation/deficiency-tickets/<ticket_id>/transition")
def transition_ticket(ticket_id):
    _, role = require_roles("SafetyOfficer", "UnitManager")
    b = body()

    # Rung 2 for the specific action requested.
    require_action_role(role, b.get("action"), TICKET_ACTION_ROLES)

    # Rung 3
    action = req_enum(b, "action", TICKET_ACTIONS)
    opt_str(b, "note")

    # Rung 5
    ticket = get_ticket(ticket_id)
    session = db.rounding_sessions[ticket["rounding_session_id"]]
    unit = db.units[session["unit_id"]]

    # Rung 7
    if role == "UnitManager" and g.user_id != unit["id"]:
        raise ApiError("ERR_UNIT_SCOPE_VIOLATION")

    state = ticket["state"]

    # Rung 13
    declared = {
        "START_WORK": ("OPEN",),
        "MARK_REMEDIATED": ("IN_PROGRESS", "ESCALATED"),
        "VERIFY": ("REMEDIATED",),
        "FAIL_VERIFICATION": ("REMEDIATED",),
        "ESCALATE": ("OPEN", "IN_PROGRESS"),
    }
    if state not in declared[action]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 16
    if action in ("VERIFY", "FAIL_VERIFICATION") and session["state"] != "CLOSED":
        raise ApiError("ERR_SESSION_NOT_CLOSED")

    if action == "START_WORK":
        ticket["state"] = "IN_PROGRESS"
        touch(ticket)
    elif action == "MARK_REMEDIATED":
        ticket["state"] = "REMEDIATED"
        touch(ticket)
    elif action == "VERIFY":
        ticket["state"] = "VERIFIED"
        ticket["verified_by_user_id"] = g.user_id
        touch(ticket)
        unit["open_deficiency_penalty_points"] = max(
            0, unit["open_deficiency_penalty_points"] - ticket["penalty_points"]
        )
        touch(unit)
        cascade.refresh_unit_posture(unit)
        standard = db.standards.get(ticket["standard_id"])
        if standard is not None:
            cascade.release_standard_from_deficient(standard)
    elif action == "FAIL_VERIFICATION":
        ticket["state"] = "OPEN"
        ticket["failed_verification_count"] += 1
        touch(ticket)
    else:  # ESCALATE
        before_points = ticket["penalty_points"]
        ticket["state"] = "ESCALATED"
        if session["round_type"] == "LIFE_SAFETY":
            ticket["severity"] = "IMMEDIATE_THREAT"
            ticket["penalty_points"] = calc.SEVERITY_POINTS["IMMEDIATE_THREAT"]
        touch(ticket)
        delta = ticket["penalty_points"] - before_points
        if delta:
            unit["open_deficiency_penalty_points"] = max(
                0, unit["open_deficiency_penalty_points"] + delta
            )
            touch(unit)
        cascade.refresh_unit_posture(unit)

    return object_response(serialize.ticket(ticket))
