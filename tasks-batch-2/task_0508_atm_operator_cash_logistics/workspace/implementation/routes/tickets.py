"""Service-ticket routes: open, read/list, acknowledge, resolve, reopen, cancel."""
from flask import Blueprint, request

import lookups
import serialize
import validate
import services.ticket as ticket_svc
from constants import FAULT_KINDS, SEVERITIES
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_array, ok_object

bp = Blueprint("tickets", __name__)


@bp.route("/service-tickets", methods=["POST"])
def open_ticket():
    _, role = authenticate()
    authorize(role, {"FieldTech", "PlatformAdmin"})
    body = validate.get_body()
    atm_id = validate.require_str(body, "atm_id")
    fault_kind = validate.require_enum(body, "fault_kind", FAULT_KINDS)
    severity = validate.optional_enum(body, "severity", SEVERITIES, "MINOR")
    atm = lookups.atm(store, atm_id)
    ticket = {
        "atm_id": atm_id,
        "fault_kind": fault_kind,
        "severity": severity,
        "status": "OPEN",
        "reopen_count": 0,
        "assigned_tech_id": None,
    }
    store.stamp_new(ticket)
    store.service_tickets[ticket["id"]] = ticket
    # Drive ATM operational_status.
    ticket_svc.apply_fault(store, atm, severity)
    return ok_object(store.clock, serialize.service_ticket(ticket), 201)


@bp.route("/service-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech"})
    ticket = lookups.service_ticket(store, tid)
    return ok_object(store.clock, serialize.service_ticket(ticket))


@bp.route("/service-tickets", methods=["GET"])
def list_tickets():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "FieldTech"})
    limit, offset = validate.parse_pagination(request.args)
    atm_id = request.args.get("atm_id")
    status = request.args.get("status")
    items = store.sorted_values(store.service_tickets)
    if atm_id is not None:
        items = [t for t in items if t["atm_id"] == atm_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = validate.paginate([serialize.service_ticket(t) for t in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


@bp.route("/service-tickets/<tid>/acknowledge", methods=["POST"])
def acknowledge_ticket(tid):
    user_id, role = authenticate()
    authorize(role, {"FieldTech"})
    ticket = lookups.service_ticket(store, tid)
    if ticket["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Ticket is not OPEN.")
    ticket["status"] = "ACKNOWLEDGED"
    ticket["assigned_tech_id"] = user_id
    store.touch(ticket)
    return ok_object(store.clock, serialize.service_ticket(ticket))


@bp.route("/service-tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    user_id, role = authenticate()
    authorize(role, {"FieldTech"})
    ticket = lookups.service_ticket(store, tid)
    # State (priority 6) precedes ownership (priority 7).
    if ticket["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "Ticket is not ACKNOWLEDGED.")
    # ERR_NOT_TICKET_OWNER (priority 7) — resolve only.
    if ticket["assigned_tech_id"] != user_id:
        raise err("ERR_NOT_TICKET_OWNER", "Acting tech is not the assigned owner.")
    ticket["status"] = "RESOLVED"
    store.touch(ticket)
    atm = store.atms.get(ticket["atm_id"])
    if atm is not None:
        ticket_svc.restore_if_clear(store, atm, ticket["id"])
    return ok_object(store.clock, serialize.service_ticket(ticket))


@bp.route("/service-tickets/<tid>/reopen", methods=["POST"])
def reopen_ticket(tid):
    _, role = authenticate()
    authorize(role, {"FieldTech"})
    ticket = lookups.service_ticket(store, tid)
    if ticket["status"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Ticket is not RESOLVED.")
    ticket["status"] = "OPEN"
    ticket["reopen_count"] = ticket["reopen_count"] + 1
    store.touch(ticket)
    atm = store.atms.get(ticket["atm_id"])
    if atm is not None:
        ticket_svc.apply_fault(store, atm, ticket["severity"])
    return ok_object(store.clock, serialize.service_ticket(ticket))


@bp.route("/service-tickets/<tid>/cancel", methods=["POST"])
def cancel_ticket(tid):
    _, role = authenticate()
    authorize(role, {"FieldTech"})
    ticket = lookups.service_ticket(store, tid)
    if ticket["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise err("ERR_INVALID_STATE", "Ticket cannot be cancelled from its current state.")
    ticket["status"] = "CANCELLED"
    store.touch(ticket)
    atm = store.atms.get(ticket["atm_id"])
    if atm is not None:
        ticket_svc.restore_if_clear(store, atm, ticket["id"])
    return ok_object(store.clock, serialize.service_ticket(ticket))
