"""MaintenanceTicket endpoints (PRD §3.2)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import new_record, require_body, req_enum, touch, get_or_404
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("maintenance_tickets", __name__)

REASONS = {"SCHEDULED_SERVICE", "DAMAGE_REPAIR", "INSPECTION"}


@bp.post("/rental-yard/maintenance-tickets")
def create_ticket():
    require_auth({"YardManager"})
    body = require_body(get_json_body())

    # Existence (PRD §2.5): equipment_unit_id.
    equipment_unit_id = body.get("equipment_unit_id")
    if not isinstance(equipment_unit_id, str):
        raise errors.invalid_request("Field 'equipment_unit_id' must be a string.")

    with LOCK:
        unit = DB.equipment_units.get(equipment_unit_id)
        if unit is None:
            raise errors.not_found()
        reason = req_enum(body, "reason", REASONS)

        # Manual pull only valid when the unit is AVAILABLE (PRD §3.2).
        if unit["availability_state"] != "AVAILABLE":
            raise errors.invalid_state(
                "A manual maintenance pull requires the unit to be AVAILABLE.")

        unit["availability_state"] = "OUT_OF_SERVICE"
        touch(unit)

        ticket = new_record({
            "equipment_unit_id": equipment_unit_id,
            "reason": reason,
            "ticket_state": "OPEN",
            "opened_by_agreement_id": None,
        })
        DB.maintenance_tickets[ticket["id"]] = ticket
    return single_response(ticket, 201)


@bp.get("/rental-yard/maintenance-tickets/<rid>")
def get_ticket(rid):
    rec = get_or_404(DB.maintenance_tickets, rid)
    return single_response(rec)


@bp.get("/rental-yard/maintenance-tickets")
def list_tickets():
    filters = {
        "equipment_unit_id": request.args.get("equipment_unit_id"),
        "opened_by_agreement_id": request.args.get("opened_by_agreement_id"),
        "ticket_state": request.args.get("ticket_state"),
    }
    items = DB.maintenance_tickets.values()
    for field, val in filters.items():
        if val is not None:
            items = [t for t in items if t.get(field) == val]
    return list_response(items)


@bp.post("/rental-yard/maintenance-tickets/<rid>/resolve")
def resolve_ticket(rid):
    require_auth({"YardManager"})
    with LOCK:
        ticket = get_or_404(DB.maintenance_tickets, rid)
        # State precondition: ticket must be OPEN (PRD §3.2, priority 7).
        if ticket["ticket_state"] != "OPEN":
            raise errors.invalid_state()
        ticket["ticket_state"] = "RESOLVED"
        touch(ticket)

        # Free the unit only when no other OPEN ticket remains (PRD §3.2).
        unit_id = ticket["equipment_unit_id"]
        other_open = any(
            t["id"] != ticket["id"]
            and t["equipment_unit_id"] == unit_id
            and t["ticket_state"] == "OPEN"
            for t in DB.maintenance_tickets.values()
        )
        if not other_open:
            unit = DB.equipment_units.get(unit_id)
            if unit is not None:
                unit["availability_state"] = "AVAILABLE"
                touch(unit)
    return single_response(ticket)
