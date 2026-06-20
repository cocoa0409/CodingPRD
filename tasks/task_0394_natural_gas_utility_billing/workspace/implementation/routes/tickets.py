"""Emergency ticket endpoints (PRD §3.13)."""

from flask import Blueprint, request

from db import store
from errors import ERR_INVALID_STATE, ERR_INVALID_REQUEST, err
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    require_enum,
    optional_bool,
    attach_common_fields,
    bump,
    paginate,
)
from services.serialize import view_ticket
from services import lookup, calc

bp = Blueprint("tickets", __name__)


@bp.route("/tickets", methods=["POST"])
def open_ticket():
    principal = authenticate()
    require_role(principal, {"CustomerService", "FieldTech", "Account"})
    with store.lock:
        body = get_body()
        require_fields(body, ["premise_meter_id", "kind"])
        premise_meter_id = require_string(body, "premise_meter_id")
        kind = require_enum(body, "kind", {"ODOR", "LEAK", "CARBON_MONOXIDE"})
        reported_indoors = optional_bool(body, "reported_indoors", default=False)

        meter = lookup.get_meter(premise_meter_id)

        account_id = body.get("account_id")
        if account_id is not None:
            if not isinstance(account_id, str):
                raise err(ERR_INVALID_REQUEST, "account_id must be a string")
            lookup.get_account(account_id)
            require_account_ownership(principal, account_id)
        else:
            # An Account principal opening a ticket acts on its own premise.
            if principal.role == "Account":
                require_account_ownership(principal, meter["account_id"])

        severity, response_due_minutes = calc.compute_ticket_severity(kind, reported_indoors)
        rec = {
            "account_id": account_id,
            "premise_meter_id": premise_meter_id,
            "kind": kind,
            "severity": severity,
            "reported_indoors": reported_indoors,
            "status": "OPEN",
            "response_due_minutes": response_due_minutes,
            "gas_locked": False,
        }
        attach_common_fields(rec)
        store.tickets[rec["id"]] = rec
        return success(view_ticket(rec), 201)


@bp.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    ticket = lookup.get_ticket(ticket_id)
    if principal.role == "Account":
        meter = store.meters.get(ticket["premise_meter_id"])
        owner = ticket.get("account_id") or (meter["account_id"] if meter else None)
        require_account_ownership(principal, owner)
    return success(view_ticket(ticket), 200)


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    account_id = request.args.get("account_id")
    premise_meter_id = request.args.get("premise_meter_id")
    records = list(store.tickets.values())
    if account_id is not None:
        records = [t for t in records if t.get("account_id") == account_id]
    if premise_meter_id is not None:
        records = [t for t in records if t["premise_meter_id"] == premise_meter_id]
    if principal.role == "Account":
        own = principal.user_id
        meter_ids = {m["id"] for m in lookup.account_meters(own)}
        records = [t for t in records
                   if t.get("account_id") == own or t["premise_meter_id"] in meter_ids]
    page, list_meta = paginate(records)
    return success([view_ticket(t) for t in page], 200, list_meta=list_meta)


@bp.route("/tickets/<ticket_id>/dispatch", methods=["POST"])
def dispatch_ticket(ticket_id):
    principal = authenticate()
    require_role(principal, {"FieldTech"})
    with store.lock:
        ticket = lookup.get_ticket(ticket_id)
        if ticket["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Ticket is not OPEN")
        ticket["status"] = "DISPATCHED"
        bump(ticket)
        return success(view_ticket(ticket), 200)


@bp.route("/tickets/<ticket_id>/make-safe", methods=["POST"])
def make_safe(ticket_id):
    principal = authenticate()
    require_role(principal, {"FieldTech"})
    with store.lock:
        ticket = lookup.get_ticket(ticket_id)
        if ticket["status"] != "DISPATCHED":
            raise err(ERR_INVALID_STATE, "Ticket is not DISPATCHED")
        ticket["status"] = "MADE_SAFE"
        bump(ticket)
        if ticket["severity"] == "GRADE_1":
            ticket["gas_locked"] = True
            meter = store.meters.get(ticket["premise_meter_id"])
            if meter is not None:
                meter["status"] = "LOCKED"
                bump(meter)
        return success(view_ticket(ticket), 200)


@bp.route("/tickets/<ticket_id>/resolve", methods=["POST"])
def resolve_ticket(ticket_id):
    principal = authenticate()
    require_role(principal, {"FieldTech"})
    with store.lock:
        ticket = lookup.get_ticket(ticket_id)
        if ticket["status"] != "MADE_SAFE":
            raise err(ERR_INVALID_STATE, "Ticket is not MADE_SAFE")
        ticket["status"] = "RESOLVED"
        bump(ticket)
        return success(view_ticket(ticket), 200)


@bp.route("/tickets/<ticket_id>/cancel", methods=["POST"])
def cancel_ticket(ticket_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        ticket = lookup.get_ticket(ticket_id)
        if ticket["status"] not in ("OPEN", "DISPATCHED"):
            raise err(ERR_INVALID_STATE, "Ticket cannot be cancelled from its current state")
        ticket["status"] = "CANCELLED"
        bump(ticket)
        return success(view_ticket(ticket), 200)
