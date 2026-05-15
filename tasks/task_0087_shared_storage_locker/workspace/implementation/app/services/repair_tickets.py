"""Repair-ticket business logic (PRD §3.8)."""
from __future__ import annotations

from typing import Any

from .. import constants
from ..auth import current_actor
from ..clock import now_iso_ms
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .compartments import get_compartment_or_404
from .serializers import serialize_repair_ticket
from .validation import require_field, require_in, require_str


def get_ticket_or_404(ticket_id: str) -> dict[str, Any]:
    store = get_store()
    t = store.repair_tickets.get(ticket_id)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", f"RepairTicket {ticket_id} not found.")
    return t


def _check_version(entity: dict[str, Any], supplied: Any) -> None:
    if supplied is None:
        return
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError("ERR_BAD_REQUEST", "version must be an integer.")
    if supplied != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")


def open_ticket(body: dict[str, Any]) -> dict[str, Any]:
    compartment_id = require_str(require_field(body, "compartment_id"), "compartment_id")
    fault_category = require_in(
        require_field(body, "fault_category"), "fault_category", constants.FAULT_CATEGORIES
    )

    comp = get_compartment_or_404(compartment_id)
    actor_id, actor_role = current_actor()

    reporter_role = "RENTER" if actor_role == "Renter" else "OPERATOR"

    ticket = common_fields_create()
    ticket.update(
        {
            "compartment_id": compartment_id,
            "cabinet_id": comp["cabinet_id"],
            "fault_category": fault_category,
            "reporter_role": reporter_role,
            "assigned_technician_id": None,
            "status": "OPEN",
            "repair_notes": None,
            "accepted_at": None,
        }
    )
    store = get_store()
    store.repair_tickets[ticket["id"]] = ticket

    # Compartment cascade to FAULT
    comp["operational_status"] = "FAULT"
    comp["fault_category"] = fault_category
    bump_version(comp)
    # Note: existing rental on this compartment is not auto-terminated.

    return serialize_repair_ticket(ticket)


def get_ticket(ticket_id: str) -> dict[str, Any]:
    ticket = get_ticket_or_404(ticket_id)
    actor_id, actor_role = current_actor()
    if actor_role == "RepairTechnician":
        # Shared op when assigned
        if ticket.get("assigned_technician_id") != actor_id:
            raise ApiError("ERR_FORBIDDEN", "Technician is not assigned to this ticket.")
    return serialize_repair_ticket(ticket)


def dispatch_ticket(ticket_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ticket = get_ticket_or_404(ticket_id)
    _check_version(ticket, body.get("version"))
    if ticket["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Cannot dispatch in status {ticket['status']}.")
    technician_id = require_str(require_field(body, "assigned_technician_id"), "assigned_technician_id")
    ticket["assigned_technician_id"] = technician_id
    ticket["status"] = "DISPATCHED"
    bump_version(ticket)
    return serialize_repair_ticket(ticket)


def repair_ticket(ticket_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ticket = get_ticket_or_404(ticket_id)
    _check_version(ticket, body.get("version"))
    if ticket["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot repair in status {ticket['status']}.")
    actor_id, _actor_role = current_actor()
    if ticket["assigned_technician_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Only the assigned technician may submit repair.")
    repair_notes = require_str(require_field(body, "repair_notes"), "repair_notes")
    ticket["repair_notes"] = repair_notes
    ticket["status"] = "REPAIRED"
    bump_version(ticket)
    return serialize_repair_ticket(ticket)


def accept_ticket(ticket_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ticket = get_ticket_or_404(ticket_id)
    _check_version(ticket, body.get("version"))
    if ticket["status"] != "REPAIRED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot accept in status {ticket['status']}.")
    ticket["status"] = "ACCEPTED"
    ticket["accepted_at"] = now_iso_ms()
    bump_version(ticket)

    # Cascade: compartment operational_status → OK; fault_category cleared
    comp = get_compartment_or_404(ticket["compartment_id"])
    comp["operational_status"] = "OK"
    comp["fault_category"] = None
    bump_version(comp)
    return serialize_repair_ticket(ticket)


def reject_ticket(ticket_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ticket = get_ticket_or_404(ticket_id)
    _check_version(ticket, body.get("version"))
    if ticket["status"] != "REPAIRED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot reject in status {ticket['status']}.")
    rejection_reason = require_str(require_field(body, "rejection_reason"), "rejection_reason")
    ticket["repair_notes"] = (ticket.get("repair_notes") or "") + f"\nrejected: {rejection_reason}"
    ticket["status"] = "REJECTED"
    bump_version(ticket)
    return serialize_repair_ticket(ticket)
