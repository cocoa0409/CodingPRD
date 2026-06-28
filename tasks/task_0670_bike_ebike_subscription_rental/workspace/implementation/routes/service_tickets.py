from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_REQUEST, ERR_BIKE_RETIRED, ERR_BIKE_ALREADY_SERVICING,
    ERR_INVALID_STATE,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_enum,
    require_string, parse_pagination, paginate,
)
from services.lookups import get_rental, get_ticket, check_rental_ownership
from services.serialize import service_ticket_view

service_tickets_bp = Blueprint("service_tickets", __name__)

ISSUE_TYPES = {"FLAT_TIRE", "BRAKE", "BATTERY", "MOTOR", "OTHER"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
VIEW_ROLES = {"OpsAdmin", "FieldTech", "Subscriber", "FleetManager"}
OPEN_TICKET_STATES = {"OPEN", "IN_PROGRESS", "REOPENED"}


@service_tickets_bp.route("/service-tickets", methods=["POST"])
def create_ticket():
    user_id, role = require_role({"Subscriber", "FleetManager", "FieldTech"})
    body = get_json_body()
    require_fields(body, ["rental_id", "issue_type", "severity", "description"])
    with db.lock:
        rental = get_rental(body["rental_id"])
        check_rental_ownership(rental, user_id, role)

        bike = db.bikes.get(rental["bike_id"])
        # Priority 6: cannot file against a rental whose bike is RETIRED.
        if bike is not None and bike["bike_status"] == "RETIRED":
            raise err(ERR_BIKE_RETIRED, "Bike has been retired/written off.")
        # Priority 9: bike already SERVICING -> mutual exclusion.
        if bike is not None and bike["bike_status"] == "SERVICING":
            raise err(ERR_BIKE_ALREADY_SERVICING, "Bike is already SERVICING.")

        require_enum(body["issue_type"], ISSUE_TYPES, "issue_type")
        require_enum(body["severity"], SEVERITIES, "severity")
        require_string(body["description"], "description")

        ticket = {
            "rental_id": rental["id"],
            "issue_type": body["issue_type"],
            "severity": body["severity"],
            "description": body["description"],
            "status": "OPEN",
            "resolution_note": None,
        }
        stamp_create(ticket)
        db.service_tickets[ticket["id"]] = ticket

        # CRITICAL freeze: bike OUT->SERVICING, rental ACTIVE->IN_SERVICE.
        if body["severity"] == "CRITICAL":
            if bike is not None and bike["bike_status"] == "OUT":
                bike["bike_status"] = "SERVICING"
                touch(bike)
            if rental["lifecycle_status"] == "ACTIVE":
                rental["lifecycle_status"] = "IN_SERVICE"
                touch(rental)

    return object_response(service_ticket_view(ticket), 201)


@service_tickets_bp.route("/service-tickets/<ticket_id>", methods=["GET"])
def fetch_ticket(ticket_id):
    require_role(VIEW_ROLES)
    ticket = get_ticket(ticket_id)
    return object_response(service_ticket_view(ticket), 200)


@service_tickets_bp.route("/service-tickets", methods=["GET"])
def list_tickets():
    require_role(VIEW_ROLES)
    limit, offset = parse_pagination()
    records = list(db.service_tickets.values())
    for field in ("rental_id", "status"):
        val = request.args.get(field)
        if val:
            records = [r for r in records if r.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response([service_ticket_view(r) for r in page], limit, offset, total)


@service_tickets_bp.route("/service-tickets/<ticket_id>/start", methods=["POST"])
def start_ticket(ticket_id):
    require_role({"FieldTech"})
    with db.lock:
        ticket = get_ticket(ticket_id)
        if ticket["status"] not in ("OPEN", "REOPENED"):
            raise err(ERR_INVALID_STATE, "Ticket must be OPEN or REOPENED to start.")
        ticket["status"] = "IN_PROGRESS"
        touch(ticket)
    return object_response(service_ticket_view(ticket), 200)


@service_tickets_bp.route("/service-tickets/<ticket_id>/resolve", methods=["POST"])
def resolve_ticket(ticket_id):
    require_role({"FieldTech"})
    body = get_json_body()
    with db.lock:
        ticket = get_ticket(ticket_id)
        if ticket["status"] != "IN_PROGRESS":
            raise err(ERR_INVALID_STATE, "Ticket must be IN_PROGRESS to resolve.")
        require_fields(body, ["resolution_note"])
        require_string(body["resolution_note"], "resolution_note")
        ticket["resolution_note"] = body["resolution_note"]
        ticket["status"] = "RESOLVED"
        touch(ticket)
    return object_response(service_ticket_view(ticket), 200)


@service_tickets_bp.route("/service-tickets/<ticket_id>/reopen", methods=["POST"])
def reopen_ticket(ticket_id):
    user_id, role = require_role({"Subscriber", "FleetManager"})
    with db.lock:
        ticket = get_ticket(ticket_id)
        rental = db.rentals.get(ticket["rental_id"])
        if rental is not None:
            check_rental_ownership(rental, user_id, role)
        if ticket["status"] != "RESOLVED":
            raise err(ERR_INVALID_STATE, "Ticket must be RESOLVED to reopen.")
        ticket["status"] = "REOPENED"
        touch(ticket)
    return object_response(service_ticket_view(ticket), 200)


@service_tickets_bp.route("/service-tickets/<ticket_id>/close", methods=["POST"])
def close_ticket(ticket_id):
    require_role({"FieldTech"})
    with db.lock:
        ticket = get_ticket(ticket_id)
        if ticket["status"] != "RESOLVED":
            raise err(ERR_INVALID_STATE, "Ticket must be RESOLVED to close.")
        ticket["status"] = "CLOSED"
        touch(ticket)

        # Conditional cascade: if rental IN_SERVICE and no other open ticket,
        # auto-return rental to ACTIVE and bike SERVICING->OUT.
        rental = db.rentals.get(ticket["rental_id"])
        if rental is not None and rental["lifecycle_status"] == "IN_SERVICE":
            others_open = any(
                t["rental_id"] == rental["id"]
                and t["id"] != ticket["id"]
                and t["status"] in OPEN_TICKET_STATES
                for t in db.service_tickets.values()
            )
            if not others_open:
                rental["lifecycle_status"] = "ACTIVE"
                touch(rental)
                bike = db.bikes.get(rental["bike_id"])
                if bike is not None and bike["bike_status"] == "SERVICING":
                    bike["bike_status"] = "OUT"
                    touch(bike)
    return object_response(service_ticket_view(ticket), 200)
