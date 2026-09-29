"""Anomaly events, escalation tickets, the operational sweep and the clock."""
from flask import Blueprint, request

import auth
import clock
import db
import serializers as ser
import services
from config import (
    CLASSIFICATIONS,
    EVENT_STATES,
    FEEDBACK_LABELS,
    ROLE_ADJUSTER,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_HOMEOWNER,
    TICKET_STAGES,
)
from errors import ApiError
from response import enum_filter, listing, ok, page_params, str_filter
from util import fmt_dt, get_body, req_datetime, req_enum, req_string

bp = Blueprint("events", __name__)


def _event(eid):
    row = db.anomaly_events.get(eid)
    if row is None:
        raise ApiError("ERR_ANOMALY_EVENT_NOT_FOUND", "No anomaly event exists with id %s." % eid)
    return row


def _ticket(tid):
    row = db.escalation_tickets.get(tid)
    if row is None:
        raise ApiError(
            "ERR_ESCALATION_TICKET_NOT_FOUND", "No escalation ticket exists with id %s." % tid
        )
    return row


# ---------------------------------------------------------------- reads
@bp.get("/anomaly-events/<eid>")
def get_event(eid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ANALYST, ROLE_ADJUSTER, ROLE_ADMIN)
    row = _event(eid)
    auth.own_event(actor, row)
    return ok(ser.anomaly_event(row))


@bp.get("/anomaly-events")
def list_events():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ANALYST, ROLE_ADJUSTER, ROLE_ADMIN)
    limit, offset = page_params()
    device_id = str_filter("device_id")
    reading_id = str_filter("telemetry_reading_id")
    classification = enum_filter("classification", CLASSIFICATIONS)
    state = enum_filter("event_state", EVENT_STATES)
    rows = list(db.anomaly_events.values())
    if actor.is_homeowner:
        rows = [e for e in rows if db.owner_of_event(e) == actor.user_id]
    if device_id is not None:
        rows = [e for e in rows if e["device_id"] == device_id]
    if reading_id is not None:
        rows = [e for e in rows if e["telemetry_reading_id"] == reading_id]
    if classification is not None:
        rows = [e for e in rows if e["classification"] == classification]
    if state is not None:
        rows = [e for e in rows if e["event_state"] == state]
    rows = db.sort_rows(rows, lambda e: (e["detected_at"], e["created_at"]))
    return listing(rows, ser.anomaly_event, limit, offset)


@bp.get("/escalation-tickets/<tid>")
def get_ticket(tid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    row = _ticket(tid)
    auth.own_ticket(actor, row)
    return ok(ser.escalation_ticket(row))


@bp.get("/escalation-tickets")
def list_tickets():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    limit, offset = page_params()
    event_id = str_filter("anomaly_event_id")
    contact_id = str_filter("notified_contact_id")
    stage = enum_filter("stage", TICKET_STAGES)
    rows = list(db.escalation_tickets.values())
    if actor.is_homeowner:
        rows = [t for t in rows if db.owner_of_ticket(t) == actor.user_id]
    if event_id is not None:
        rows = [t for t in rows if t["anomaly_event_id"] == event_id]
    if contact_id is not None:
        rows = [t for t in rows if t.get("notified_contact_id") == contact_id]
    if stage is not None:
        rows = [t for t in rows if t["stage"] == stage]
    rows = db.sort_rows(rows, lambda t: t["created_at"])
    return listing(rows, ser.escalation_ticket, limit, offset)


# ---------------------------------------------------------------- writes
@bp.post("/anomaly-events/<eid>/feedback")
def feedback(eid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    event = _event(eid)
    body = get_body(request)
    label = req_enum(body, "label", FEEDBACK_LABELS)
    auth.own_event(actor, event)
    device_row = db.devices[event["device_id"]]
    auth.alive_device(device_row)
    if event["event_state"] not in ("DETECTED", "ALERTED", "ESCALATED", "SUPPRESSED"):
        raise ApiError(
            "ERR_EVENT_NOT_ACTIONABLE", "A closed anomaly event accepts no further feedback."
        )
    now = clock.now()
    event["feedback_label"] = label
    if label == "TRUE_POSITIVE":
        event["event_state"] = "RESOLVED"
        event["resolved_at"] = now
        db.touch(event)
        services.expire_pending_ticket(event, "EVENT_CLOSED")
    else:
        event["event_state"] = "FALSE_POSITIVE"
        db.touch(event)
        services.expire_pending_ticket(event, "EVENT_CLOSED")
        services.false_positive_tuning(event, device_row)
    return ok(ser.anomaly_event(event))


@bp.post("/anomaly-events/<eid>/resolve")
def resolve(eid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    event = _event(eid)
    body = get_body(request)
    note = req_string(body, "resolution_note", 1, 280)
    auth.own_event(actor, event)
    device_row = db.devices[event["device_id"]]
    auth.alive_device(device_row)
    if event["event_state"] not in ("DETECTED", "ALERTED", "ESCALATED", "SUPPRESSED"):
        raise ApiError(
            "ERR_EVENT_NOT_ACTIONABLE", "A closed anomaly event accepts no further resolution."
        )
    ticket = db.ticket_for_event(eid)
    if ticket is not None and ticket["stage"] in (
        "PENDING_HOMEOWNER",
        "PENDING_EMERGENCY_CONTACT",
    ):
        raise ApiError(
            "ERR_EVENT_NOT_ACTIONABLE",
            "The escalation ticket must be acknowledged or expired before resolution.",
        )
    event["event_state"] = "RESOLVED"
    event["resolved_at"] = clock.now()
    event["resolution_note"] = note
    db.touch(event)
    services.expire_pending_ticket(event, "EVENT_CLOSED")
    return ok(ser.anomaly_event(event))


@bp.post("/escalation-tickets/<tid>/acknowledge")
def acknowledge(tid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    ticket = _ticket(tid)
    auth.own_ticket(actor, ticket)
    owner_id = db.owner_of_ticket(ticket)
    auth.alive_id(owner_id)
    if ticket["stage"] not in ("PENDING_HOMEOWNER", "PENDING_EMERGENCY_CONTACT"):
        raise ApiError("ERR_TICKET_NOT_PENDING", "This ticket has already left the ladder.")
    ticket["stage"] = "ACKNOWLEDGED"
    ticket["acknowledged_at"] = clock.now()
    ticket["acknowledged_by_user_id"] = actor.user_id
    db.touch(ticket)
    return ok(ser.escalation_ticket(ticket))


@bp.post("/ops-sweeps")
def ops_sweep():
    auth.guard(ROLE_ADMIN)
    report = services.run_sweep()
    return ok(
        {
            "swept_at": fmt_dt(report["swept_at"]),
            "modes_reverted": report["modes_reverted"],
            "tickets_escalated": report["tickets_escalated"],
            "tickets_expired": report["tickets_expired"],
            "transfers_expired": report["transfers_expired"],
        }
    )


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.guard(ROLE_ADMIN)
    body = get_body(request)
    target = req_datetime(body, "to_iso8601")
    clock.set_now(target)
    return ok({"current_utc": fmt_dt(clock.now())})
