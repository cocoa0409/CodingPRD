"""ServiceTicket endpoints (PRD 3.8): open, list, get, start, resolve, reopen."""
from flask import Blueprint, request

from common import get_json_body, get_or_404, list_response, require_bool, require_enum
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize
from services.inventory import rederive_machine_service

bp = Blueprint("tickets", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")
ISSUE_TYPES = {"JAM", "TELEMETRY_ALERT", "VANDALISM", "COIN_MECH"}


@bp.route("/operations/machines/<machine_id>/service-tickets", methods=["POST"])
@require_roles("FieldOps", "HostManager")
def open_ticket(machine_id):
    machine = get_or_404("machines", machine_id)
    body = get_json_body()
    issue_type = require_enum(body, "issue_type", ISSUE_TYPES)
    blocking = require_bool(body, "blocking", allow_missing=True, default=False)

    obj = {
        "machine_id": machine_id,
        "issue_type": issue_type,
        "blocking": blocking,
        "status": "OPEN",
    }
    stamp_create(obj)
    db.tickets[obj["id"]] = obj

    # if blocking, machine -> FROZEN
    if blocking:
        rederive_machine_service(machine)

    return object_response(serialize.ticket(obj), 201)


@bp.route("/operations/machines/<machine_id>/service-tickets", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_machine_tickets(machine_id):
    get_or_404("machines", machine_id)
    rows = [t for t in db.tickets.values() if t["machine_id"] == machine_id]
    return list_response(rows, serialize.ticket)


@bp.route("/operations/service-tickets", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_tickets():
    rows = list(db.tickets.values())
    machine_id = request.args.get("machine_id")
    if machine_id is not None:
        rows = [t for t in rows if t["machine_id"] == machine_id]
    return list_response(rows, serialize.ticket)


@bp.route("/operations/service-tickets/<ticket_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_ticket(ticket_id):
    obj = get_or_404("tickets", ticket_id)
    return object_response(serialize.ticket(obj))


@bp.route("/operations/service-tickets/<ticket_id>/start", methods=["POST"])
@require_roles("FieldOps")
def start_ticket(ticket_id):
    ticket = get_or_404("tickets", ticket_id)
    if ticket["status"] == "OPEN":
        ticket["status"] = "IN_PROGRESS"
    elif ticket["status"] == "REOPENED":
        ticket["status"] = "IN_PROGRESS"
    else:
        raise ApiError("ERR_TICKET_NOT_OPEN", "Ticket is not in a startable state")
    touch(ticket)
    # starting work does not change the freeze posture
    return object_response(serialize.ticket(ticket))


@bp.route("/operations/service-tickets/<ticket_id>/resolve", methods=["POST"])
@require_roles("FieldOps")
def resolve_ticket(ticket_id):
    ticket = get_or_404("tickets", ticket_id)
    if ticket["status"] != "IN_PROGRESS":
        raise ApiError("ERR_TICKET_NOT_IN_PROGRESS", "Ticket is not IN_PROGRESS")
    ticket["status"] = "RESOLVED"
    touch(ticket)
    # if no blocking ticket remains active on the machine -> IN_SERVICE
    machine = db.machines.get(ticket["machine_id"])
    if machine is not None:
        rederive_machine_service(machine)
    return object_response(serialize.ticket(ticket))


@bp.route("/operations/service-tickets/<ticket_id>/reopen", methods=["POST"])
@require_roles("FieldOps")
def reopen_ticket(ticket_id):
    ticket = get_or_404("tickets", ticket_id)
    if ticket["status"] != "RESOLVED":
        raise ApiError("ERR_TICKET_NOT_RESOLVED", "Ticket is not RESOLVED")
    ticket["status"] = "REOPENED"
    touch(ticket)
    # if blocking, machine -> FROZEN
    machine = db.machines.get(ticket["machine_id"])
    if machine is not None and ticket["blocking"]:
        rederive_machine_service(machine)
    return object_response(serialize.ticket(ticket))
