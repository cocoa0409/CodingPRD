"""MoulderSetupSlot endpoints (PRD §3.4): half-open windows, overlap, changeover buffer."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_int, require_existence)
from response import success, list_response, parse_pagination

bp = Blueprint("slots", __name__)

SLOT_STATUSES = ("BOOKED", "COMPLETED", "CANCELLED")
CHANGEOVER_HOURS = 2


def species_family(species):
    return "PAINT" if species == "PAINT_GRADE" else "STAIN"


def serialize(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "machine_id": s["machine_id"],
        "species": s["species"],
        "start_hour": s["start_hour"],
        "end_hour": s["end_hour"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.post("/moulder-setup-slots")
def create_slot():
    _, role = get_context()
    require_role(role, "ProductionLead")
    body = raw_body()
    # Rung 3: body FK existence in declared input order.
    if body.get("program_id") is not None:
        program = require_existence(db.machining_programs, body["program_id"],
                                    "ERR_PROGRAM_NOT_FOUND", "MachiningProgram")
    else:
        program = None
    if body.get("machine_id") is not None:
        machine = require_existence(db.moulder_machines, body["machine_id"],
                                    "ERR_MACHINE_NOT_FOUND", "MoulderMachine")
    else:
        machine = None
    # Rung 4: payload, including the structural window rule.
    validate_fields(body, required=("program_id", "machine_id", "start_hour", "end_hour"))
    start_hour = req_int(body, "start_hour")
    end_hour = req_int(body, "end_hour")
    if end_hour <= start_hour:
        raise err("ERR_INVALID_SLOT_HOURS", "end_hour must be strictly later than start_hour")
    # Rung 6: the program must be awaiting setup.
    if program["status"] != "CREATED":
        raise err("ERR_PROGRAM_NOT_AWAITING_SETUP", "Slot booking requires program CREATED")
    # Rung 7 (safety): the machine's tooling must support the order's species.
    order = db.orders.get(program["order_id"])
    species = order["species"] if order is not None else None
    if species not in machine["supported_species"]:
        raise err("ERR_MACHINE_SPECIES_UNSUPPORTED",
                  "Machine does not support species %s" % species)
    # Rung 8: overlap, then cross-family changeover buffer.
    new_family = species_family(species)
    for existing in db.moulder_setup_slots.values():
        if existing["machine_id"] != machine["id"] or existing["status"] not in ("BOOKED", "COMPLETED"):
            continue
        if start_hour < existing["end_hour"] and existing["start_hour"] < end_hour:
            raise err("ERR_MACHINE_SLOT_OVERLAP",
                      "Window overlaps an existing slot on the machine")
        if species_family(existing["species"]) != new_family:
            gap = max(start_hour - existing["end_hour"], existing["start_hour"] - end_hour)
            if gap < CHANGEOVER_HOURS:
                raise err("ERR_CHANGEOVER_BUFFER_VIOLATION",
                          "Cross-species-family gap must be at least 2 hours")
    rec = db.new_record()
    rec.update({
        "program_id": program["id"],
        "machine_id": machine["id"],
        "species": species,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "status": "BOOKED",
    })
    db.moulder_setup_slots[rec["id"]] = rec
    # Cascade: program CREATED -> SETUP_BOOKED.
    program["status"] = "SETUP_BOOKED"
    db.touch(program)
    return success(serialize(rec), status=201)


@bp.get("/moulder-setup-slots")
def list_slots():
    get_context()
    limit, offset = parse_pagination(request.args)
    machine_id = request.args.get("machine_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = [s for s in db.moulder_setup_slots.values()
             if (machine_id is None or s["machine_id"] == machine_id)
             and (program_id is None or s["program_id"] == program_id)
             and (status is None or s["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/moulder-setup-slots/<sid>")
def get_slot(sid):
    get_context()
    slot = require_existence(db.moulder_setup_slots, sid, "ERR_SLOT_NOT_FOUND", "MoulderSetupSlot")
    return success(serialize(slot))


@bp.put("/moulder-setup-slots/<sid>/status")
def transition_slot(sid):
    _, role = get_context()
    require_role(role, "ProductionLead")
    slot = require_existence(db.moulder_setup_slots, sid, "ERR_SLOT_NOT_FOUND", "MoulderSetupSlot")
    body = raw_body()
    validate_fields(body, required=("target_status",))
    target = req_string(body, "target_status")
    current = slot["status"]

    if target == "COMPLETED":
        if current != "BOOKED":
            raise err("ERR_INVALID_SLOT_STATUS_TRANSITION",
                      "Slot cannot transition from %s to COMPLETED" % current)
        slot["status"] = "COMPLETED"
        program = db.machining_programs.get(slot["program_id"])
        if program is not None and program["status"] == "SETUP_BOOKED":
            program["status"] = "PROVEN"
            db.touch(program)

    elif target == "CANCELLED":
        if current != "BOOKED":
            raise err("ERR_INVALID_SLOT_STATUS_TRANSITION",
                      "Slot cannot transition from %s to CANCELLED" % current)
        slot["status"] = "CANCELLED"
        # Explicit cancel returns the program to CREATED.
        program = db.machining_programs.get(slot["program_id"])
        if program is not None and program["status"] == "SETUP_BOOKED":
            program["status"] = "CREATED"
            db.touch(program)

    elif target in SLOT_STATUSES:
        raise err("ERR_INVALID_SLOT_STATUS_TRANSITION",
                  "Slot cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_SLOT_STATUS_TRANSITION",
                  "Unknown slot status: %s" % target)

    db.touch(slot)
    return success(serialize(slot))
