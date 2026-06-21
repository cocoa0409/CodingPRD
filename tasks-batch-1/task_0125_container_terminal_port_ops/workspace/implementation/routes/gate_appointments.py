"""Gate appointment endpoints + lifecycle and the gate-out cascade (PRD §3.4)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from db import MAX_NO_SHOWS
from errors import (
    APIError,
    ERR_CROSS_ENTITY_STATE,
    ERR_GATE_SLOT_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_SHOW_CAP,
    ERR_OUTSIDE_WINDOW,
    ERR_STACKING_VIOLATION,
)
from middleware import require
from response import ok_array, ok_object
from services import demurrage, serialize
from services.clash import gate_conflict
from services.common import (
    clock_dt,
    get_body,
    paginate,
    parse_dt,
    require_enum,
    require_present,
    require_str,
    stamp_create,
    touch,
)
from services.lookups import fk_container, path_appt

bp = Blueprint("gate_appointments", __name__)


def _validate_60min(start, end):
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    if end_dt - start_dt != timedelta(minutes=60):
        raise APIError(ERR_INVALID_REQUEST, 422, "window_end must be exactly 60 minutes after window_start")


@bp.post("/gate-appointments")
@require("GateOperator")
def book_appointment():
    body = get_body()
    # FK existence (priority 4)
    container_id = require_present(body, "container_id")
    if not isinstance(container_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "container_id must be a string")
    fk_container(container_id)
    # shape (priority 5)
    truck_plate = require_str(body, "truck_plate", non_empty=True)
    window_start = require_present(body, "window_start")
    window_end = require_present(body, "window_end")
    parse_dt(window_start)
    parse_dt(window_end)
    _validate_60min(window_start, window_end)
    # gate slot clash (priority 15)
    conflict = gate_conflict(container_id, window_start, window_end, exclude_id=None)
    if conflict is not None:
        raise APIError(ERR_GATE_SLOT_CONFLICT, 409, "gate slot overlaps an existing appointment")

    rec = stamp_create({
        "container_id": container_id,
        "truck_plate": truck_plate,
        "window_start": window_start,
        "window_end": window_end,
        "status": "BOOKED",
        "no_show_count": 0,
    })
    db.gate_appointments[rec["id"]] = rec
    return ok_object(serialize.gate_appointment(rec), 201)


@bp.get("/gate-appointments/<aid>")
@require("TerminalAdmin", "GateOperator")
def get_appointment(aid):
    rec = path_appt(aid)
    return ok_object(serialize.gate_appointment(rec))


@bp.get("/gate-appointments")
@require("TerminalAdmin", "GateOperator")
def list_appointments():
    container_id = request.args.get("container_id")
    rows = list(db.gate_appointments.values())
    if container_id is not None:
        rows = [a for a in rows if a["container_id"] == container_id]
    items, limit, offset, total = paginate(rows, serialize.gate_appointment)
    return ok_array(items, limit, offset, total)


@bp.get("/gate-appointments/<aid>/eirs")
@require("TerminalAdmin", "GateOperator")
def list_appointment_eirs(aid):
    path_appt(aid)
    rows = [e for e in db.eirs.values() if e["gate_appointment_id"] == aid]
    items, limit, offset, total = paginate(rows, serialize.eir)
    return ok_array(items, limit, offset, total)


@bp.post("/gate-appointments/<aid>/check-in")
@require("GateOperator")
def check_in(aid):
    appt = path_appt(aid)
    if appt["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "appointment is not BOOKED")
    now = clock_dt()
    start = parse_dt(appt["window_start"])
    end = parse_dt(appt["window_end"])
    if not (start <= now < end):
        raise APIError(ERR_OUTSIDE_WINDOW, 409, "check-in outside [window_start, window_end)")
    appt["status"] = "ARRIVED"
    touch(appt)
    return ok_object(serialize.gate_appointment(appt))


@bp.post("/gate-appointments/<aid>/mark-no-show")
@require("GateOperator")
def mark_no_show(aid):
    appt = path_appt(aid)
    if appt["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "appointment is not BOOKED")
    now = clock_dt()
    end = parse_dt(appt["window_end"])
    if not (now >= end):
        raise APIError(ERR_OUTSIDE_WINDOW, 409, "slot has not fully elapsed")
    appt["status"] = "NO_SHOW"
    appt["no_show_count"] += 1
    touch(appt)
    return ok_object(serialize.gate_appointment(appt))


@bp.post("/gate-appointments/<aid>/reschedule")
@require("GateOperator")
def reschedule(aid):
    appt = path_appt(aid)
    body = get_body()
    # shape (priority 5)
    window_start = require_present(body, "window_start")
    window_end = require_present(body, "window_end")
    parse_dt(window_start)
    parse_dt(window_end)
    _validate_60min(window_start, window_end)
    # state (priority 7)
    if appt["status"] != "NO_SHOW":
        raise APIError(ERR_INVALID_STATE, 409, "appointment is not NO_SHOW")
    # no-show cap (priority 17): count > MAX_NO_SHOWS bars reschedule
    if appt["no_show_count"] > MAX_NO_SHOWS:
        raise APIError(ERR_NO_SHOW_CAP, 409, "no-show cap exceeded; cannot reschedule")
    # gate slot clash (priority 15)
    conflict = gate_conflict(appt["container_id"], window_start, window_end, exclude_id=aid)
    if conflict is not None:
        raise APIError(ERR_GATE_SLOT_CONFLICT, 409, "gate slot overlaps an existing appointment")
    appt["window_start"] = window_start
    appt["window_end"] = window_end
    appt["status"] = "BOOKED"
    touch(appt)
    return ok_object(serialize.gate_appointment(appt))


@bp.post("/gate-appointments/<aid>/cancel")
@require("GateOperator")
def cancel_appointment(aid):
    appt = path_appt(aid)
    if appt["status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "appointment is not BOOKED")
    appt["status"] = "CANCELLED"
    touch(appt)
    return ok_object(serialize.gate_appointment(appt))


@bp.post("/gate-appointments/<aid>/fulfill")
@require("GateOperator")
def fulfill(aid):
    appt = path_appt(aid)
    body = get_body()
    # shape (priority 5): condition + damage_note pairing
    condition = require_enum(body, "condition", {"SOUND", "DAMAGED"})
    damage_note = body.get("damage_note")
    if condition == "DAMAGED":
        if not isinstance(damage_note, str) or damage_note.strip() == "":
            raise APIError(ERR_INVALID_REQUEST, 422, "damage_note required when condition is DAMAGED")
    else:
        if damage_note is not None:
            raise APIError(ERR_INVALID_REQUEST, 422, "damage_note must be null/omitted when condition is SOUND")

    container = db.containers.get(appt["container_id"])
    # state (priority 7): appointment ARRIVED and container GROUNDED
    if appt["status"] != "ARRIVED":
        raise APIError(ERR_INVALID_STATE, 409, "appointment is not ARRIVED")
    if container is None or container["handling_status"] != "GROUNDED":
        raise APIError(ERR_INVALID_STATE, 409, "container is not GROUNDED")
    # cross-entity (priority 8): customs must be CLEARED
    if container["customs_status"] != "CLEARED":
        raise APIError(ERR_CROSS_ENTITY_STATE, 409, "container customs_status is not CLEARED")
    # stacking (priority 9): nothing stacked directly above this slot
    slot_id = container["yard_slot_id"]
    for s in db.yard_slots.values():
        if s["below_slot_id"] == slot_id and s["status"] == "OCCUPIED":
            raise APIError(ERR_STACKING_VIOLATION, 409, "a box is stacked on top of this container")

    # ---- cascade ----------------------------------------------------------
    chargeable_days, due = demurrage.compute(container)
    container["demurrage_due_cents"] = due
    container["handling_status"] = "GATED_OUT"
    # free the vacated yard slot
    slot = db.yard_slots.get(slot_id)
    if slot is not None:
        slot["occupied_by_container_id"] = None
        slot["status"] = "EMPTY"
        touch(slot)
    container["yard_slot_id"] = None
    touch(container)
    appt["status"] = "FULFILLED"
    touch(appt)
    # GATE_OUT EIR (append-only)
    eir = stamp_create({
        "container_id": container["id"],
        "gate_appointment_id": aid,
        "direction": "GATE_OUT",
        "condition": condition,
        "damage_note": damage_note,
        "recorded_at": db.clock_now(),
    }, versioned=False)
    db.eirs[eir["id"]] = eir
    # DemurrageInvoice
    invoice = stamp_create({
        "container_id": container["id"],
        "chargeable_days": chargeable_days,
        "amount_cents": due,
        "status": "ISSUED",
    })
    db.demurrage_invoices[invoice["id"]] = invoice
    return ok_object(serialize.gate_appointment(appt))
