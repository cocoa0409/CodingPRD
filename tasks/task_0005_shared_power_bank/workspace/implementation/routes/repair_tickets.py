from flask import Blueprint, request
from auth import require_role
from db import db, bump
from envelope import success
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_STATE
from validation import optional_bool, occ_check
from serializers import serialize_repair_ticket

bp = Blueprint("repair_tickets", __name__)


@bp.get("/repair-tickets/<ticket_id>")
def get_ticket(ticket_id):
    require_role({"Admin", "Operator"})
    t = db.repair_tickets.get(ticket_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Repair ticket not found")
    return success(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<ticket_id>/assign")
def assign_ticket(ticket_id):
    uid, _ = require_role({"Operator"})
    t = db.repair_tickets.get(ticket_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Repair ticket not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(t, body)
    if t["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket is not OPEN")
    t["status"] = "ASSIGNED"
    t["assigned_operator_id"] = uid
    bump(t)
    return success(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<ticket_id>/hold")
def hold_ticket(ticket_id):
    require_role({"Operator"})
    t = db.repair_tickets.get(ticket_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Repair ticket not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(t, body)
    # Auto-transition ASSIGNED→IN_PROGRESS on first hold/resolve.
    if t["status"] == "ASSIGNED":
        t["status"] = "IN_PROGRESS"
    if t["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket is not IN_PROGRESS")
    t["status"] = "ON_HOLD"
    bump(t)
    return success(serialize_repair_ticket(t))


@bp.post("/repair-tickets/<ticket_id>/resume")
def resume_ticket(ticket_id):
    require_role({"Operator"})
    t = db.repair_tickets.get(ticket_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Repair ticket not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(t, body)
    if t["status"] != "ON_HOLD":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket is not ON_HOLD")
    t["status"] = "IN_PROGRESS"
    bump(t)
    return success(serialize_repair_ticket(t))


def _resolve_device_target(ticket: dict) -> None:
    if ticket["target_type"] != "DEVICE":
        return
    device = db.devices.get(ticket["target_id"])
    if device is None:
        return
    if device["status"] == "FAULTY":
        device["status"] = "AVAILABLE"
        bump(device)
    # Slot transitions FAULTY → EMPTY/OCCUPIED based on whether slot.device_id is null.
    for s in db.slots.values():
        if s["slot_status"] != "FAULTY":
            continue
        if s.get("device_id") == device["id"] or (
            device.get("current_cabinet_id") == s["cabinet_id"]
            and device.get("current_slot_index") == s["slot_index"]
        ):
            s["slot_status"] = "OCCUPIED" if s.get("device_id") else "EMPTY"
            bump(s)


@bp.post("/repair-tickets/<ticket_id>/resolve")
def resolve_ticket(ticket_id):
    require_role({"Operator"})
    t = db.repair_tickets.get(ticket_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Repair ticket not found")
    body = request.get_json(silent=True) or {}
    if body:
        occ_check(t, body)
    cancel = optional_bool(body, "cancel") if body else None

    if cancel is True:
        if t["status"] != "ASSIGNED":
            raise APIError(ERR_INVALID_STATE, 409, "Cancel only valid from ASSIGNED")
        t["status"] = "CANCELLED"
        bump(t)
        return success(serialize_repair_ticket(t))

    # Auto-transition ASSIGNED → IN_PROGRESS on first resolve.
    if t["status"] == "ASSIGNED":
        t["status"] = "IN_PROGRESS"
    if t["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket is not IN_PROGRESS")

    t["status"] = "RESOLVED"
    bump(t)
    _resolve_device_target(t)
    return success(serialize_repair_ticket(t))
