"""Remote troubleshooting and the depth-five escalation cascade (PRD 3.7)."""

from flask import Blueprint, request

import sla
import serializers as S
from counters import household_of_ticket
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from firmware_svc import block_pending_rollouts
from ladder import (begin, gates, invalid_state, opt_str, req_enum, resolve,
                    scope_household, touch)
from money import REMOTE_FAILURE_ESCALATION_COUNT
from store import clock, db, new_row, sort_rows

bp = Blueprint("sessions", __name__)
PREFIX = "/smart-home-support"


@bp.post(PREFIX + "/tickets/<tid>/remote-sessions")
def open_session(tid):
    ctx = begin(("SupportAgent",))
    found = resolve(ticket=tid)
    ticket = found["ticket"]
    household = household_of_ticket(ticket)
    gates(household=household, ticket=ticket)

    status = ticket.get("workflow_status")
    if status not in ("TRIAGED", "REOPENED", "REMOTE_DIAG"):
        invalid_state("A remote session may only be opened from TRIAGED, REOPENED or REMOTE_DIAG.")
    if status == "REMOTE_DIAG":
        # The self-loop is permitted only when no session of this ticket is
        # still IN_PROGRESS.
        for row in db.remote_sessions.values():
            if row.get("ticket_id") == ticket["id"] and row.get("status") == "IN_PROGRESS":
                invalid_state("A remote session of this ticket is still IN_PROGRESS.")

    prior = len([r for r in db.remote_sessions.values() if r.get("ticket_id") == ticket["id"]])
    row = new_row()
    row.update({
        "ticket_id": ticket["id"],
        "agent_user_id": ctx.user_id,
        "session_index": prior + 1,
        "started_at": clock.now_iso(),
        "ended_at": None,
        "status": "IN_PROGRESS",
        "outcome": None,
        "diagnostic_notes": None,
    })
    db.remote_sessions[row["id"]] = row
    ticket["workflow_status"] = "REMOTE_DIAG"
    touch(ticket)
    return created(S.remote_session(row))


@bp.get(PREFIX + "/remote-sessions")
def list_sessions():
    begin(("PlatformAdmin", "SupportAgent", "Owner"))
    limit, offset = read_pagination(request.args)
    tid = request.args.get("ticket_id")
    rows = [r for r in db.remote_sessions.values()
            if tid is None or r.get("ticket_id") == tid]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.remote_session(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/remote-sessions/<sid>")
def read_session(sid):
    ctx = begin(("PlatformAdmin", "SupportAgent", "Owner"))
    found = resolve(session=sid)
    session = found["session"]
    ticket = db.tickets.get(session.get("ticket_id"))
    scope_household(ctx, ticket.get("household_id") if ticket else None)
    return ok(S.remote_session(session))


@bp.post(PREFIX + "/remote-sessions/<sid>/complete")
def complete_session(sid):
    ctx = begin(("SupportAgent",))
    found = resolve(session=sid)
    session = found["session"]
    ticket = db.tickets.get(session.get("ticket_id"))
    household = household_of_ticket(ticket)
    scope_household(ctx, ticket.get("household_id") if ticket else None)
    # Rung 21 sits above rung 27: a bad outcome on an already-completed
    # session still reports ERR_INVALID_ENUM.
    outcome = req_enum(ctx.body, "outcome")
    diagnostic_notes = opt_str(ctx.body, "diagnostic_notes")
    gates(household=household, ticket=ticket)

    if session.get("status") != "IN_PROGRESS":
        invalid_state("Only an IN_PROGRESS session may be completed.")
    if ticket is None or ticket.get("workflow_status") != "REMOTE_DIAG":
        invalid_state("The owning ticket must be in REMOTE_DIAG.")

    # Hop 1 -- the session.
    session["outcome"] = outcome
    session["ended_at"] = clock.now_iso()
    session["status"] = "COMPLETED"
    if diagnostic_notes is not None:
        session["diagnostic_notes"] = diagnostic_notes
    touch(session)

    if outcome == "RESOLVED":
        ticket["workflow_status"] = "RESOLVED"
        ticket["resolved_at"] = clock.now_iso()
        if ticket.get("survey_solicited_at") is None:
            ticket["survey_solicited_at"] = ticket["resolved_at"]
        sla.settle_met(ticket)
        touch(ticket)
        return ok(S.remote_session(session))

    escalate = False
    reason = None
    if outcome == "FAILED":
        # Hop 2 -- the comparison is on the POST-increment value, so the third
        # failed completion escalates and the second does not.
        ticket["remote_session_failure_count"] = (
            ticket.get("remote_session_failure_count") or 0) + 1
        if ticket["remote_session_failure_count"] >= REMOTE_FAILURE_ESCALATION_COUNT:
            escalate = True
            reason = "FAILURE_THRESHOLD"
    else:  # HARDWARE_FAULT -- escalates immediately at any failure count.
        escalate = True
        reason = "HARDWARE_FAULT"

    if escalate:
        ticket["workflow_status"] = "DISPATCH_PENDING"
        ticket["dispatch_status"] = "REQUIRED"
        ticket["escalation_reason"] = reason
        device = db.devices.get(ticket.get("device_id")) if ticket.get("device_id") else None
        # Hop 3 -- the device.
        if device is not None and device.get("lifecycle_status") == "ACTIVE":
            device["lifecycle_status"] = "SERVICE_HOLD"
            touch(device)
            # Hops 4 and 5 -- the rollouts and the campaigns.
            block_pending_rollouts(device)
    touch(ticket)
    return ok(S.remote_session(session))
