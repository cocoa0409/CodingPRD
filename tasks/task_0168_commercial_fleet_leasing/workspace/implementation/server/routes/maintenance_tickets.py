"""MaintenanceTicket routes (§3.5)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..common import as_int, bump, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import maintenance_view
from ..store import store


bp = Blueprint("maintenance_tickets", __name__)


@bp.post("/vehicles/<vehicle_id>/maintenance-tickets")
@require_auth("FleetManager", "VendorOps")
def open_ticket(vehicle_id: str):
    body = get_json_body()
    require_fields(body, "ticket_kind")
    kind = body["ticket_kind"]
    if kind not in ("PM", "REPAIR"):
        raise ApiError("ERR_VALIDATION", "ticket_kind must be PM or REPAIR")
    estimate = body.get("estimate_cents", 0) or 0
    estimate = as_int(estimate, "estimate_cents", min_value=0)

    with store.lock:
        v = store.vehicles.get(vehicle_id)
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")

        ticket = {
            "vehicle_id": vehicle_id,
            "ticket_kind": kind,
            "opened_at_odometer": int(v.get("odometer_current_miles", 0)),
            "estimate_cents": estimate,
            "actual_cents": 0,
            "ticket_status": "OPEN",
        }
        stamp_new(ticket)
        store.maintenance_tickets[ticket["id"]] = ticket
    return respond(maintenance_view(ticket), 201)


@bp.post("/maintenance-tickets/<ticket_id>/start")
@require_auth("VendorOps")
def start_ticket(ticket_id: str):
    with store.lock:
        t = store.maintenance_tickets.get(ticket_id)
        if t is None:
            raise ApiError("ERR_NOT_FOUND", "MaintenanceTicket not found")
        if t["ticket_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Ticket is not OPEN")
        v = store.vehicles.get(t["vehicle_id"])
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")
        if v["vehicle_status"] not in ("ALLOCATED", "GROUNDED"):
            raise ApiError("ERR_INVALID_STATE", "Vehicle is not ALLOCATED or GROUNDED")

        t["ticket_status"] = "IN_SHOP"
        bump(t)
        v["vehicle_status"] = "IN_SHOP"
        bump(v)
    return respond(maintenance_view(t), 200)


@bp.post("/maintenance-tickets/<ticket_id>/close")
@require_auth("VendorOps")
def close_ticket(ticket_id: str):
    body = get_json_body()
    require_fields(body, "actual_cents")
    actual = as_int(body["actual_cents"], "actual_cents", min_value=0)

    with store.lock:
        t = store.maintenance_tickets.get(ticket_id)
        if t is None:
            raise ApiError("ERR_NOT_FOUND", "MaintenanceTicket not found")
        if t["ticket_status"] != "IN_SHOP":
            raise ApiError("ERR_INVALID_STATE", "Ticket is not IN_SHOP")
        if actual <= 0:
            raise ApiError("ERR_ACTUAL_COST_REQUIRED", "actual_cents must be > 0")

        t["actual_cents"] = actual
        t["ticket_status"] = "CLOSED"
        bump(t)

        v = store.vehicles.get(t["vehicle_id"])
        if v is not None:
            # Restore: ALLOCATED if tied to a current_lease_id, else GROUNDED
            if v.get("current_lease_id"):
                v["vehicle_status"] = "ALLOCATED"
            else:
                v["vehicle_status"] = "GROUNDED"
            bump(v)
    return respond(maintenance_view(t), 200)


@bp.post("/maintenance-tickets/<ticket_id>/cancel")
@require_auth("FleetManager")
def cancel_ticket(ticket_id: str):
    with store.lock:
        t = store.maintenance_tickets.get(ticket_id)
        if t is None:
            raise ApiError("ERR_NOT_FOUND", "MaintenanceTicket not found")
        if t["ticket_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Ticket is not OPEN")
        t["ticket_status"] = "CANCELLED"
        bump(t)
    return respond(maintenance_view(t), 200)
