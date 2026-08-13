"""MaintenanceTicket endpoints (PRD §3.6)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain
from util import (body, req_str, req_int, req_enum, new_resource, touch,
                  pagination_params, paginate, sort_by_created, iso_z)

bp = Blueprint("maintenance", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}
OPENED_REASONS = {"SCHEDULED_CYCLE", "DAMAGE_REPAIR", "CONDITION_THRESHOLD", "POST_FLIGHT_INSPECTION"}


@bp.route("/backline/maintenance-tickets", methods=["POST"])
def create_ticket():
    auth = get_auth()
    require_roles(auth, {"WarehouseTech", "OpsManager"})
    data = body()
    gear_unit_id = req_str(data, "gear_unit_id")
    unit = domain.get_gear_unit(gear_unit_id)
    opened_reason = req_enum(data, "opened_reason", OPENED_REASONS)
    ticket = new_resource()
    ticket.update({
        "gear_unit_id": gear_unit_id,
        "opened_reason": opened_reason,
        "status": "OPEN",
        "opened_at": iso_z(store.current_utc),
        "closed_at": None,
        "service_cost_cents": None,
        "condition_delta": None,
    })
    store.maintenance_tickets[ticket["id"]] = ticket
    # Opening a ticket against an AVAILABLE unit pulls it into MAINTENANCE (§3.6)
    if unit.get("status") == "AVAILABLE":
        unit["status"] = "MAINTENANCE"
        touch(unit)
    return success_object(domain.serialize(ticket), status=201)


@bp.route("/backline/maintenance-tickets/<ticket_id>", methods=["GET"])
def fetch_ticket(ticket_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    ticket = domain.get_ticket(ticket_id)
    return success_object(domain.serialize(ticket), status=200)


@bp.route("/backline/maintenance-tickets", methods=["GET"])
def list_tickets():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    gear_unit_id = request.args.get("gear_unit_id")
    status = request.args.get("status")
    items = list(store.maintenance_tickets.values())
    if gear_unit_id is not None:
        items = [t for t in items if t.get("gear_unit_id") == gear_unit_id]
    if status is not None:
        items = [t for t in items if t.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(t) for t in page], meta, status=200)


@bp.route("/backline/maintenance-tickets/<ticket_id>/start", methods=["POST"])
def start_ticket(ticket_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    ticket = domain.get_ticket(ticket_id)
    if ticket["status"] != "OPEN":
        raise errors.invalid_state("Ticket must be OPEN to start")
    ticket["status"] = "IN_PROGRESS"
    touch(ticket)
    return success_object(domain.serialize(ticket), status=200)


@bp.route("/backline/maintenance-tickets/<ticket_id>/await-parts", methods=["POST"])
def await_parts(ticket_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    ticket = domain.get_ticket(ticket_id)
    if ticket["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Ticket must be IN_PROGRESS to await parts")
    ticket["status"] = "AWAITING_PARTS"
    touch(ticket)
    return success_object(domain.serialize(ticket), status=200)


@bp.route("/backline/maintenance-tickets/<ticket_id>/resume", methods=["POST"])
def resume_ticket(ticket_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    ticket = domain.get_ticket(ticket_id)
    if ticket["status"] != "AWAITING_PARTS":
        raise errors.invalid_state("Ticket must be AWAITING_PARTS to resume")
    ticket["status"] = "IN_PROGRESS"
    touch(ticket)
    return success_object(domain.serialize(ticket), status=200)


@bp.route("/backline/maintenance-tickets/<ticket_id>/complete", methods=["POST"])
def complete_ticket(ticket_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    ticket = domain.get_ticket(ticket_id)
    if ticket["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Ticket must be IN_PROGRESS to complete")
    data = body()
    service_cost = req_int(data, "service_cost_cents", minimum=0)
    condition_delta = req_int(data, "condition_delta", minimum=0)
    if condition_delta > 100:
        raise errors.invalid_request("condition_delta must be between 0 and 100")
    unit = domain.get_gear_unit(ticket["gear_unit_id"])
    # Restore the unit: condition climbs (capped at 100), service-day count
    # resets, active reservation clears, and the unit returns to AVAILABLE
    unit["condition_score"] = min(100, unit.get("condition_score", 100) + condition_delta)
    unit["rental_days_since_service"] = 0
    unit["active_reservation_id"] = None
    if unit.get("status") == "MAINTENANCE":
        unit["status"] = "AVAILABLE"
    touch(unit)
    ticket["service_cost_cents"] = service_cost
    ticket["condition_delta"] = condition_delta
    ticket["status"] = "COMPLETED"
    ticket["closed_at"] = iso_z(store.current_utc)
    touch(ticket)
    return success_object(domain.serialize(ticket), status=200)


@bp.route("/backline/maintenance-tickets/<ticket_id>/cancel", methods=["POST"])
def cancel_ticket(ticket_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    ticket = domain.get_ticket(ticket_id)
    if ticket["status"] not in {"OPEN", "AWAITING_PARTS"}:
        raise errors.invalid_state("Only OPEN or AWAITING_PARTS tickets may be cancelled")
    ticket["status"] = "CANCELLED"
    ticket["closed_at"] = iso_z(store.current_utc)
    touch(ticket)
    return success_object(domain.serialize(ticket), status=200)
