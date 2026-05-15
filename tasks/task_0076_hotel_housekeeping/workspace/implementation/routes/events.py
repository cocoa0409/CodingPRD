"""Inbound event endpoints: PMS sync, engineering update, laundry return, clock advance."""

from flask import Blueprint, request, g

from db import DB, LOCK
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH,
    ERR_MOVEMENT_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
    ERR_TICKET_NOT_FOUND,
    ERR_TICKET_NOT_DISPATCHED,
)
from middleware import auth_required
from response import success_response
from services.audit import append_audit
from services.calculations import recompute_discrepancy
from services.cleaning_task_service import create_and_dispatch
from services.common import (
    bump,
    require_body_dict,
    require_enum,
    require_field,
)
from services.room_machine import (
    ALL_NON_OUT_OF_ORDER,
    inspected_grace_sweep,
    transition_room,
)
from services.serializers import (
    serialize_linen_movement,
    serialize_maintenance_ticket,
    serialize_room,
)
from services.time_util import advance, now_utc, utc_now_iso


bp = Blueprint("events", __name__)


PMS_EVENT_TYPES = {"CHECK_IN", "CHECK_OUT", "DAILY_TURN", "OCCUPANCY_SYNC"}
PMS_OCCUPANCIES = {"VACANT", "OCCUPIED", "DUE_OUT", "NO_SHOW"}
ENGINEERING_NEW_STATUS = {"IN_REPAIR", "REPAIR_COMPLETED"}


def _find_room_by_number(number):
    for r in DB["rooms"].values():
        if r["room_number"] == number:
            return r
    return None


# --------------------------------------------------------------------------- #
# PMS Sync
# --------------------------------------------------------------------------- #
@bp.route("/_events/pms-sync", methods=["POST"])
@auth_required(["SystemIntegration"])
def pms_sync():
    body = require_body_dict(request.get_json(silent=True))
    room_number = require_field(body, "room_number", str)
    event_type = require_enum(body, "event_type", PMS_EVENT_TYPES)
    pms_occupancy = require_enum(body, "pms_occupancy", PMS_OCCUPANCIES)

    with LOCK:
        room = _find_room_by_number(room_number)
        if room is None:
            raise_error(ERR_ROOM_NOT_FOUND, "Room not found by room_number")

        prev_pms = room.get("pms_occupancy")
        room["pms_occupancy"] = pms_occupancy
        room["pms_synced_at"] = utc_now_iso()
        bump(room)

        room["_last_actor"] = "pms"

        # Drive the room state machine per event_type
        if event_type == "CHECK_IN":
            if room["status"] == "VACANT_CLEAN":
                transition_room(
                    room, "OCCUPIED_CLEAN",
                    change_reason="PMS_SYNC",
                    actor_id="pms",
                    write_audit=True,
                )
        elif event_type == "DAILY_TURN":
            if room["status"] == "OCCUPIED_CLEAN":
                transition_room(
                    room, "OCCUPIED_DIRTY",
                    change_reason="PMS_SYNC",
                    actor_id="pms",
                    write_audit=True,
                )
        elif event_type == "CHECK_OUT":
            if room["status"] == "OCCUPIED_DIRTY":
                transition_room(
                    room, "VACANT_DIRTY",
                    change_reason="PMS_SYNC",
                    actor_id="pms",
                    write_audit=True,
                )
                # Auto-create CHECK_OUT cleaning task
                create_and_dispatch(
                    room=room,
                    task_source="CHECK_OUT",
                    expedite_flag=False,
                )
        # OCCUPANCY_SYNC drives no status transition

        # Always recompute discrepancy + audit
        recompute_discrepancy(room, audit_on_flip=True)
        append_audit(
            actor_id="pms",
            actor_role=None,
            action_type="EVENT_INGESTED",
            subject_entity="Room",
            subject_id=room["id"],
            detail={
                "event_type": event_type,
                "previous_pms_occupancy": prev_pms,
                "new_pms_occupancy": pms_occupancy,
            },
        )
    return success_response(serialize_room(room))


# --------------------------------------------------------------------------- #
# Engineering update
# --------------------------------------------------------------------------- #
@bp.route("/_events/engineering-update", methods=["POST"])
@auth_required(["SystemIntegration"])
def engineering_update():
    body = require_body_dict(request.get_json(silent=True))
    ticket_id = require_field(body, "ticket_id", str)
    new_status = require_enum(body, "new_status", ENGINEERING_NEW_STATUS)

    with LOCK:
        t = DB["maintenance_tickets"].get(ticket_id)
        if t is None:
            raise_error(ERR_TICKET_NOT_FOUND, "Ticket not found")
        if new_status == "IN_REPAIR":
            if t["status"] != "DISPATCHED":
                raise_error(ERR_TICKET_NOT_DISPATCHED,
                            "Ticket is not in DISPATCHED state")
            t["status"] = "IN_REPAIR"
            bump(t)
        elif new_status == "REPAIR_COMPLETED":
            if t["status"] != "IN_REPAIR":
                raise_error(ERR_TICKET_NOT_DISPATCHED,
                            "Ticket is not in IN_REPAIR state")
            t["status"] = "REPAIR_COMPLETED"
            t["completed_at"] = utc_now_iso()
            bump(t)
        append_audit(
            actor_id="engineering",
            actor_role=None,
            action_type="EVENT_INGESTED",
            subject_entity="MaintenanceTicket",
            subject_id=t["id"],
            detail={"new_status": new_status},
        )
    return success_response(serialize_maintenance_ticket(t))


# --------------------------------------------------------------------------- #
# Laundry return
# --------------------------------------------------------------------------- #
@bp.route("/_events/laundry-return", methods=["POST"])
@auth_required(["SystemIntegration"])
def laundry_return():
    body = require_body_dict(request.get_json(silent=True))
    movement_id = require_field(body, "movement_id", str)
    returned_q = require_field(body, "returned_quantity", int)
    loss_q = require_field(body, "loss_quantity", int)
    damage_q = require_field(body, "damage_quantity", int)
    for label, val in (("returned_quantity", returned_q),
                       ("loss_quantity", loss_q),
                       ("damage_quantity", damage_q)):
        if isinstance(val, bool) or val < 0:
            raise_error(ERR_INVALID_REQUEST,
                        f"{label} must be a non-negative integer")

    with LOCK:
        m = DB["linen_movements"].get(movement_id)
        if m is None:
            raise_error(ERR_MOVEMENT_NOT_FOUND, "Movement not found")
        if m["status"] != "SENT_TO_LAUNDRY":
            raise_error(ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH,
                        "Movement is not in SENT_TO_LAUNDRY state")
        sent = int(m.get("sent_to_laundry_quantity", 0))
        if returned_q + loss_q + damage_q != sent:
            raise_error(ERR_LAUNDRY_RETURN_QUANTITY_MISMATCH,
                        "returned+loss+damage must equal sent_to_laundry_quantity")
        m["returned_quantity"] = returned_q
        m["loss_quantity"] = loss_q
        m["damage_quantity"] = damage_q
        if loss_q + damage_q > 0:
            m["status"] = "LOSS_REPORTED"
        else:
            m["status"] = "RESOLVED"
            m["folio_charge_cents"] = 0
        append_audit(
            actor_id="laundry",
            actor_role=None,
            action_type="EVENT_INGESTED",
            subject_entity="LinenMovement",
            subject_id=m["id"],
            detail={
                "returned_quantity": returned_q,
                "loss_quantity": loss_q,
                "damage_quantity": damage_q,
            },
        )
    return success_response(serialize_linen_movement(m))


# --------------------------------------------------------------------------- #
# Clock advance
# --------------------------------------------------------------------------- #
@bp.route("/_clock/advance", methods=["POST"])
@auth_required(["SystemIntegration"])
def clock_advance():
    body = require_body_dict(request.get_json(silent=True))
    minutes = require_field(body, "minutes", int)
    if isinstance(minutes, bool):
        raise_error(ERR_INVALID_REQUEST, "minutes must be an integer")
    with LOCK:
        advance(int(minutes))
        # Sweep 1: INSPECTED-grace
        inspected_grace_sweep()
        # Sweep 2: re-evaluate early-check-in priority on PENDING/ASSIGNED tasks
        from services.calculations import refresh_priority
        for t in DB["cleaning_tasks"].values():
            if t["status"] in {"PENDING", "ASSIGNED"}:
                room = DB["rooms"].get(t["room_id"])
                if room is not None:
                    refresh_priority(t, room)
        now_iso = utc_now_iso()
    return success_response({"now": now_iso})
